set(DOCKSR_SCALER_SHADER "${CMAKE_CURRENT_BINARY_DIR}/scale.comp.spv")
add_custom_command(
    OUTPUT "${DOCKSR_SCALER_SHADER}"
    COMMAND "${Vulkan_GLSLANG_VALIDATOR_EXECUTABLE}" -V --target-env vulkan1.1
            -o "${DOCKSR_SCALER_SHADER}" "${PROJECT_SOURCE_DIR}/shaders/scale.comp"
    DEPENDS "${PROJECT_SOURCE_DIR}/shaders/scale.comp"
    VERBATIM
    COMMENT "Compiling the Dock SR reference scaling shader"
)
add_custom_target(docksr_scaler_shader DEPENDS "${DOCKSR_SCALER_SHADER}")
add_library(docksr_vulkan_scaler engine.cpp scaler.cpp)
add_dependencies(docksr_vulkan_scaler docksr_scaler_shader)
target_compile_features(docksr_vulkan_scaler PUBLIC cxx_std_20)
target_link_libraries(docksr_vulkan_scaler PUBLIC Vulkan::Vulkan docksr_image)
target_include_directories(docksr_vulkan_scaler PUBLIC "${PROJECT_SOURCE_DIR}/include")
target_compile_definitions(docksr_vulkan_scaler PRIVATE DOCKSR_SHADER_PATH="${DOCKSR_SCALER_SHADER}")
if(MSVC)
    target_compile_options(docksr_vulkan_scaler PRIVATE /W4)
else()
    target_compile_options(docksr_vulkan_scaler PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_CLI)
    add_executable(docksr-bench main.cpp)
    target_compile_features(docksr-bench PRIVATE cxx_std_20)
    target_link_libraries(docksr-bench PRIVATE docksr_vulkan_scaler)
    if(MSVC)
        target_compile_options(docksr-bench PRIVATE /W4)
    else()
        target_compile_options(docksr-bench PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endif()

if(BUILD_TESTING)
    add_executable(docksr-vulkan-engine-tests scaler_tests.cpp)
    target_link_libraries(docksr-vulkan-engine-tests PRIVATE docksr_vulkan_scaler)
    add_test(NAME vulkan_engine_correctness COMMAND docksr-vulkan-engine-tests)
    set_tests_properties(vulkan_engine_correctness PROPERTIES
        LABELS "vulkan;correctness" SKIP_RETURN_CODE 77 TIMEOUT 120)
    if(BUILD_CLI)
        find_package(Python3 QUIET COMPONENTS Interpreter)
        if(Python3_Interpreter_FOUND)
            add_test(NAME vulkan_scaler_correctness
                     COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tests/vulkan_correctness.py"
                             "$<TARGET_FILE:docksr-bench>")
            set_tests_properties(vulkan_scaler_correctness PROPERTIES
                LABELS "vulkan;correctness" SKIP_RETURN_CODE 77 TIMEOUT 180)
            add_test(NAME vulkan_shader_relocation
                     COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tests/test_shader_relocation.py"
                             "$<TARGET_FILE:docksr-bench>" "${DOCKSR_SCALER_SHADER}")
            set_tests_properties(vulkan_shader_relocation PROPERTIES
                LABELS "vulkan;packaging" SKIP_RETURN_CODE 77 TIMEOUT 90)
        endif()
    endif()
endif()
