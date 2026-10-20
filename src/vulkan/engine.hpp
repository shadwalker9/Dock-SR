#pragma once

// Shared implementation for the benchmark CLI and reusable preview scaler.
// No rendering/scaling pipeline is duplicated in either consumer.
#include <docksr/vulkan/benchmark.hpp>
#include <docksr/vulkan/scaler.hpp>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace docksr::vulkan::detail {
using Clock = std::chrono::steady_clock;
inline constexpr std::uint64_t default_fence_timeout_ns = 60'000'000'000ULL;

inline void check(VkResult result, std::string_view operation) {
    if (result != VK_SUCCESS) {
        throw std::runtime_error(std::string(operation) + " failed (VkResult " +
                                 std::to_string(result) + ")");
    }
}

struct Buffer {
    VkBuffer handle = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    void* mapped = nullptr;
    VkDeviceSize bytes = 0;
    bool coherent = false;
};

struct Context {
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties properties{};
    VkPhysicalDeviceMemoryProperties memory_properties{};
    std::vector<VkExtensionProperties> extensions;
    std::string driver_name;
    std::string driver_info;
    VkQueueFamilyProperties family_properties{};
    std::uint32_t family = 0;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    Buffer input;
    Buffer output;
    VkDescriptorSetLayout descriptor_layout = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    VkDescriptorPool descriptor_pool = VK_NULL_HANDLE;
    VkDescriptorSet descriptor_set = VK_NULL_HANDLE;
    VkCommandPool command_pool = VK_NULL_HANDLE;
    VkCommandBuffer command = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VkQueryPool queries = VK_NULL_HANDLE;
    bool timestamps = false;
    std::string timestamp_status;
    bool in_flight = false;

    Context() = default;
    Context(const Context&) = delete;
    Context& operator=(const Context&) = delete;
    ~Context() {
        // A timed-out submission can still own these allocations. Do not wait
        // indefinitely or free memory underneath it while CPU fallback runs.
        // The failed driver context is quarantined until process teardown.
        if (in_flight) return;
        if (device != VK_NULL_HANDLE) {
            release_scaler();
            vkDestroyDevice(device, nullptr);
        }
        if (instance) vkDestroyInstance(instance, nullptr);
    }

    void destroy_buffer(Buffer& buffer) const {
        if (buffer.mapped) vkUnmapMemory(device, buffer.memory);
        if (buffer.handle) vkDestroyBuffer(device, buffer.handle, nullptr);
        if (buffer.memory) vkFreeMemory(device, buffer.memory, nullptr);
        buffer = {};
    }

    void release_scaler() noexcept {
        if (in_flight || device == VK_NULL_HANDLE) return;
        if (queries) vkDestroyQueryPool(device, queries, nullptr);
        if (fence) vkDestroyFence(device, fence, nullptr);
        if (command_pool) vkDestroyCommandPool(device, command_pool, nullptr);
        if (pipeline) vkDestroyPipeline(device, pipeline, nullptr);
        if (pipeline_layout) vkDestroyPipelineLayout(device, pipeline_layout, nullptr);
        if (descriptor_pool) vkDestroyDescriptorPool(device, descriptor_pool, nullptr);
        if (descriptor_layout) vkDestroyDescriptorSetLayout(device, descriptor_layout, nullptr);
        queries = VK_NULL_HANDLE;
        fence = VK_NULL_HANDLE;
        command_pool = VK_NULL_HANDLE;
        command = VK_NULL_HANDLE;
        pipeline = VK_NULL_HANDLE;
        pipeline_layout = VK_NULL_HANDLE;
        descriptor_pool = VK_NULL_HANDLE;
        descriptor_set = VK_NULL_HANDLE;
        descriptor_layout = VK_NULL_HANDLE;
        destroy_buffer(output);
        destroy_buffer(input);
    }

    bool has_extension(std::string_view name) const {
        return std::any_of(extensions.begin(), extensions.end(), [&](const auto& extension) {
            return name == extension.extensionName;
        });
    }

    void initialize_device() {
        std::uint32_t loader_version = VK_API_VERSION_1_0;
        const auto enumerate_version = reinterpret_cast<PFN_vkEnumerateInstanceVersion>(
            vkGetInstanceProcAddr(VK_NULL_HANDLE, "vkEnumerateInstanceVersion"));
        if (enumerate_version) check(enumerate_version(&loader_version), "Enumerate Vulkan version");
        if (loader_version < VK_API_VERSION_1_1) {
            throw Unavailable("Vulkan 1.1 loader is required");
        }
        VkApplicationInfo application{};
        application.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        application.pApplicationName = "Dock SR reference scaler";
        application.applicationVersion = VK_MAKE_VERSION(0, 1, 0);
        application.apiVersion = VK_API_VERSION_1_1;
        VkInstanceCreateInfo instance_info{};
        instance_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
        instance_info.pApplicationInfo = &application;
        const auto instance_result = vkCreateInstance(&instance_info, nullptr, &instance);
        if (instance_result == VK_ERROR_INCOMPATIBLE_DRIVER || instance_result == VK_ERROR_INITIALIZATION_FAILED) {
            throw Unavailable("No usable Vulkan 1.1 implementation (VkResult " + std::to_string(instance_result) + ")");
        }
        check(instance_result, "Create Vulkan instance");
        std::uint32_t count = 0;
        check(vkEnumeratePhysicalDevices(instance, &count, nullptr), "Count Vulkan devices");
        if (count == 0) throw Unavailable("No Vulkan physical devices available");
        std::vector<VkPhysicalDevice> devices(count);
        check(vkEnumeratePhysicalDevices(instance, &count, devices.data()), "Enumerate Vulkan devices");
        int best_score = -1;
        for (const auto candidate : devices) {
            VkPhysicalDeviceProperties candidate_properties{};
            vkGetPhysicalDeviceProperties(candidate, &candidate_properties);
            if (candidate_properties.apiVersion < VK_API_VERSION_1_1) continue;
            std::uint32_t queue_count = 0;
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queue_count, nullptr);
            std::vector<VkQueueFamilyProperties> families(queue_count);
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queue_count, families.data());
            for (std::uint32_t index = 0; index < queue_count; ++index) {
                if ((families[index].queueFlags & VK_QUEUE_COMPUTE_BIT) == 0 || families[index].queueCount == 0) continue;
                int score = 10;
                if (candidate_properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) score = 100;
                if (candidate_properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU) score = 90;
                if (candidate_properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU) score = 20;
                if (score > best_score) {
                    best_score = score;
                    physical = candidate;
                    properties = candidate_properties;
                    family = index;
                    family_properties = families[index];
                }
                break;
            }
        }
        if (!physical) throw Unavailable("No Vulkan 1.1 device with a compute queue available");
        vkGetPhysicalDeviceMemoryProperties(physical, &memory_properties);
        std::uint32_t extension_count = 0;
        check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &extension_count, nullptr), "Count device extensions");
        extensions.resize(extension_count);
        check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &extension_count, extensions.data()), "Enumerate device extensions");
        if (properties.apiVersion >= VK_API_VERSION_1_2 || has_extension(VK_KHR_DRIVER_PROPERTIES_EXTENSION_NAME)) {
            VkPhysicalDeviceDriverProperties driver{};
            driver.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES;
            VkPhysicalDeviceProperties2 expanded{};
            expanded.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
            expanded.pNext = &driver;
            vkGetPhysicalDeviceProperties2(physical, &expanded);
            driver_name = driver.driverName;
            driver_info = driver.driverInfo;
        }
        timestamps = family_properties.timestampValidBits > 0 &&
                     properties.limits.timestampComputeAndGraphics == VK_TRUE &&
                     std::isfinite(properties.limits.timestampPeriod) && properties.limits.timestampPeriod > 0;
        timestamp_status = timestamps ? "supported" : "unavailable: compute timestamps or valid bits not supported";
        const float priority = 1.0F;
        VkDeviceQueueCreateInfo queue_info{};
        queue_info.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        queue_info.queueFamilyIndex = family;
        queue_info.queueCount = 1;
        queue_info.pQueuePriorities = &priority;
        VkDeviceCreateInfo device_info{};
        device_info.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
        device_info.queueCreateInfoCount = 1;
        device_info.pQueueCreateInfos = &queue_info;
        check(vkCreateDevice(physical, &device_info, nullptr, &device), "Create Vulkan device");
        vkGetDeviceQueue(device, family, 0, &queue);
    }

    void create_buffer(Buffer& buffer, VkDeviceSize bytes) {
        if (bytes > properties.limits.maxStorageBufferRange) {
            throw std::runtime_error("Requested buffer exceeds this device's maxStorageBufferRange");
        }
        buffer.bytes = bytes;
        VkBufferCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        info.size = bytes;
        info.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        check(vkCreateBuffer(device, &info, nullptr, &buffer.handle), "Create persistent storage buffer");
        VkMemoryRequirements requirements{};
        vkGetBufferMemoryRequirements(device, buffer.handle, &requirements);
        std::optional<std::uint32_t> memory_type;
        for (std::uint32_t index = 0; index < memory_properties.memoryTypeCount; ++index) {
            const auto flags = memory_properties.memoryTypes[index].propertyFlags;
            if ((requirements.memoryTypeBits & (1U << index)) != 0 &&
                (flags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) != 0) {
                if (!memory_type || (flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0) {
                    memory_type = index;
                    buffer.coherent = (flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0;
                    if (buffer.coherent) break;
                }
            }
        }
        if (!memory_type) throw std::runtime_error("Device has no host-visible storage-buffer memory type");
        VkMemoryAllocateInfo allocation{};
        allocation.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocation.allocationSize = requirements.size;
        allocation.memoryTypeIndex = *memory_type;
        check(vkAllocateMemory(device, &allocation, nullptr, &buffer.memory), "Allocate persistent storage-buffer memory");
        check(vkBindBufferMemory(device, buffer.handle, buffer.memory, 0), "Bind persistent storage buffer");
        check(vkMapMemory(device, buffer.memory, 0, VK_WHOLE_SIZE, 0, &buffer.mapped), "Map persistent storage buffer");
    }

    void synchronize_host_memory(const Buffer& buffer, bool flush) const {
        if (buffer.coherent) return;
        VkMappedMemoryRange range{};
        range.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;
        range.memory = buffer.memory;
        range.offset = 0;
        range.size = VK_WHOLE_SIZE;
        if (flush) check(vkFlushMappedMemoryRanges(device, 1, &range), "Flush mapped input");
        else check(vkInvalidateMappedMemoryRanges(device, 1, &range), "Invalidate mapped output");
    }

    void initialize_scaler(const ScaleConfiguration& configuration, const std::vector<std::uint32_t>& shader) {
        const auto groups_x = (configuration.output_width + 15U) / 16U;
        const auto groups_y = (configuration.output_height + 15U) / 16U;
        if (properties.limits.maxComputeWorkGroupInvocations < 256 ||
            properties.limits.maxComputeWorkGroupSize[0] < 16 || properties.limits.maxComputeWorkGroupSize[1] < 16 ||
            properties.limits.maxComputeWorkGroupCount[0] < groups_x || properties.limits.maxComputeWorkGroupCount[1] < groups_y ||
            properties.limits.maxPushConstantsSize < sizeof(ScaleConfiguration)) {
            throw std::runtime_error("Compute workgroup or push-constant limits do not support this scaler");
        }
        create_buffer(input, VkDeviceSize(configuration.input_width) * configuration.input_height * sizeof(std::uint32_t));
        create_buffer(output, VkDeviceSize(configuration.output_width) * configuration.output_height * sizeof(std::uint32_t));
        const std::array<VkDescriptorSetLayoutBinding, 2> bindings{{
            {0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
            {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}}};
        VkDescriptorSetLayoutCreateInfo descriptor_info{};
        descriptor_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
        descriptor_info.bindingCount = static_cast<std::uint32_t>(bindings.size());
        descriptor_info.pBindings = bindings.data();
        check(vkCreateDescriptorSetLayout(device, &descriptor_info, nullptr, &descriptor_layout), "Create descriptor layout");
        VkPushConstantRange push_range{VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(ScaleConfiguration)};
        VkPipelineLayoutCreateInfo layout_info{};
        layout_info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
        layout_info.setLayoutCount = 1;
        layout_info.pSetLayouts = &descriptor_layout;
        layout_info.pushConstantRangeCount = 1;
        layout_info.pPushConstantRanges = &push_range;
        check(vkCreatePipelineLayout(device, &layout_info, nullptr, &pipeline_layout), "Create pipeline layout");
        VkShaderModuleCreateInfo shader_info{};
        shader_info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        shader_info.codeSize = shader.size() * sizeof(std::uint32_t);
        shader_info.pCode = shader.data();
        VkShaderModule shader_module = VK_NULL_HANDLE;
        check(vkCreateShaderModule(device, &shader_info, nullptr, &shader_module), "Create scaler shader module");
        VkPipelineShaderStageCreateInfo stage{};
        stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        stage.module = shader_module;
        stage.pName = "main";
        VkComputePipelineCreateInfo pipeline_info{};
        pipeline_info.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
        pipeline_info.stage = stage;
        pipeline_info.layout = pipeline_layout;
        const auto pipeline_result = vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pipeline_info, nullptr, &pipeline);
        vkDestroyShaderModule(device, shader_module, nullptr);
        check(pipeline_result, "Create scaler pipeline");
        VkDescriptorPoolSize pool_size{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2};
        VkDescriptorPoolCreateInfo pool_info{};
        pool_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
        pool_info.maxSets = 1;
        pool_info.poolSizeCount = 1;
        pool_info.pPoolSizes = &pool_size;
        check(vkCreateDescriptorPool(device, &pool_info, nullptr, &descriptor_pool), "Create descriptor pool");
        VkDescriptorSetAllocateInfo set_info{};
        set_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
        set_info.descriptorPool = descriptor_pool;
        set_info.descriptorSetCount = 1;
        set_info.pSetLayouts = &descriptor_layout;
        check(vkAllocateDescriptorSets(device, &set_info, &descriptor_set), "Allocate descriptor set");
        const std::array<VkDescriptorBufferInfo, 2> buffer_infos{{
            {input.handle, 0, input.bytes}, {output.handle, 0, output.bytes}}};
        std::array<VkWriteDescriptorSet, 2> writes{};
        for (std::size_t index = 0; index < writes.size(); ++index) {
            writes[index].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
            writes[index].dstSet = descriptor_set;
            writes[index].dstBinding = static_cast<std::uint32_t>(index);
            writes[index].descriptorCount = 1;
            writes[index].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
            writes[index].pBufferInfo = &buffer_infos[index];
        }
        vkUpdateDescriptorSets(device, static_cast<std::uint32_t>(writes.size()), writes.data(), 0, nullptr);
        VkCommandPoolCreateInfo command_pool_info{};
        command_pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        command_pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        command_pool_info.queueFamilyIndex = family;
        check(vkCreateCommandPool(device, &command_pool_info, nullptr, &command_pool), "Create command pool");
        VkCommandBufferAllocateInfo command_info{};
        command_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        command_info.commandPool = command_pool;
        command_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        command_info.commandBufferCount = 1;
        check(vkAllocateCommandBuffers(device, &command_info, &command), "Allocate command buffer");
        VkFenceCreateInfo fence_info{};
        fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        check(vkCreateFence(device, &fence_info, nullptr, &fence), "Create dispatch fence");
        if (timestamps) {
            VkQueryPoolCreateInfo query_info{};
            query_info.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;
            query_info.queryType = VK_QUERY_TYPE_TIMESTAMP;
            query_info.queryCount = 2;
            check(vkCreateQueryPool(device, &query_info, nullptr, &queries), "Create timestamp queries");
        }
    }
};

struct Sample {
    std::uint32_t index;
    std::uint32_t frame;
    double host_ms;
    std::optional<double> gpu_ms;
};

inline Sample dispatch(Context& context, const ScaleConfiguration& configuration,
                const std::vector<std::uint32_t>& input, std::uint32_t index, std::uint32_t frame,
                std::uint64_t fence_timeout_ns = default_fence_timeout_ns) {
    if (context.in_flight) throw std::runtime_error("Vulkan context is unavailable after an incomplete dispatch");
    const auto begin = Clock::now();
    std::memcpy(context.input.mapped, input.data(), static_cast<std::size_t>(context.input.bytes));
    context.synchronize_host_memory(context.input, true);
    check(vkResetFences(context.device, 1, &context.fence), "Reset dispatch fence");
    check(vkResetCommandBuffer(context.command, 0), "Reset dispatch command buffer");
    VkCommandBufferBeginInfo command_info{};
    command_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    command_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check(vkBeginCommandBuffer(context.command, &command_info), "Begin dispatch commands");
    VkBufferMemoryBarrier upload_barrier{};
    upload_barrier.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
    upload_barrier.srcAccessMask = VK_ACCESS_HOST_WRITE_BIT;
    upload_barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    upload_barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    upload_barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    upload_barrier.buffer = context.input.handle;
    upload_barrier.offset = 0;
    upload_barrier.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(context.command, VK_PIPELINE_STAGE_HOST_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 1, &upload_barrier, 0, nullptr);
    if (context.timestamps) {
        vkCmdResetQueryPool(context.command, context.queries, 0, 2);
        vkCmdWriteTimestamp(context.command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, context.queries, 0);
    }
    vkCmdBindPipeline(context.command, VK_PIPELINE_BIND_POINT_COMPUTE, context.pipeline);
    vkCmdBindDescriptorSets(context.command, VK_PIPELINE_BIND_POINT_COMPUTE, context.pipeline_layout,
                            0, 1, &context.descriptor_set, 0, nullptr);
    vkCmdPushConstants(context.command, context.pipeline_layout, VK_SHADER_STAGE_COMPUTE_BIT,
                        0, sizeof(configuration), &configuration);
    vkCmdDispatch(context.command, (configuration.output_width + 15U) / 16U,
                   (configuration.output_height + 15U) / 16U, 1);
    if (context.timestamps) {
        vkCmdWriteTimestamp(context.command, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, context.queries, 1);
    }
    VkBufferMemoryBarrier readback_barrier{};
    readback_barrier.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
    readback_barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    readback_barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    readback_barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    readback_barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    readback_barrier.buffer = context.output.handle;
    readback_barrier.offset = 0;
    readback_barrier.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(context.command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                         0, 0, nullptr, 1, &readback_barrier, 0, nullptr);
    check(vkEndCommandBuffer(context.command), "End dispatch commands");
    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &context.command;
    context.in_flight = true;
    check(vkQueueSubmit(context.queue, 1, &submit, context.fence), "Submit scaling dispatch");
    check(vkWaitForFences(context.device, 1, &context.fence, VK_TRUE, fence_timeout_ns), "Wait for scaling dispatch");
    context.in_flight = false;
    context.synchronize_host_memory(context.output, false);
    const auto end = Clock::now();
    Sample sample{index, frame, std::chrono::duration<double, std::milli>(end - begin).count(), std::nullopt};
    if (context.timestamps) {
        std::array<std::uint64_t, 2> timestamps{};
        check(vkGetQueryPoolResults(context.device, context.queries, 0, 2, sizeof(timestamps),
                                   timestamps.data(), sizeof(std::uint64_t), VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT),
              "Read dispatch timestamps");
        const auto bits = context.family_properties.timestampValidBits;
        const auto mask = bits >= 64 ? std::numeric_limits<std::uint64_t>::max() : ((std::uint64_t{1} << bits) - 1);
        const auto ticks = (timestamps[1] - timestamps[0]) & mask;
        sample.gpu_ms = double(ticks) * double(context.properties.limits.timestampPeriod) / 1'000'000.0;
    }
    return sample;
}

std::vector<std::uint32_t> load_shader();
} // namespace docksr::vulkan::detail
