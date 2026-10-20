add_library(docksr_preview_core controller.cpp)
target_include_directories(docksr_preview_core PUBLIC "${PROJECT_SOURCE_DIR}/include")
target_compile_features(docksr_preview_core PUBLIC cxx_std_20)
target_link_libraries(docksr_preview_core PUBLIC docksr_image docksr_core)

option(DOCKSR_PREVIEW_VULKAN "Use the optional Vulkan scaler in the standalone preview" ON)
if(DOCKSR_PREVIEW_VULKAN AND TARGET docksr_vulkan_scaler)
    target_link_libraries(docksr_preview_core PRIVATE docksr_vulkan_scaler)
    target_compile_definitions(docksr_preview_core PRIVATE DOCKSR_PREVIEW_VULKAN=1)
endif()

add_executable(docksr-preview main.cpp)
target_link_libraries(docksr-preview PRIVATE docksr_preview_core X11::X11)
target_compile_features(docksr-preview PRIVATE cxx_std_20)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(docksr_preview_core PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(docksr-preview PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_TESTING)
    add_executable(docksr-preview-tests "${PROJECT_SOURCE_DIR}/tests/preview_tests.cpp")
    target_link_libraries(docksr-preview-tests PRIVATE docksr_preview_core)
    add_test(NAME docksr-preview-headless COMMAND docksr-preview-tests)
    set_tests_properties(docksr-preview-headless PROPERTIES TIMEOUT 90)
    add_test(NAME docksr-preview-cli COMMAND "${Python3_EXECUTABLE}"
             "${PROJECT_SOURCE_DIR}/tests/test_preview_cli.py" "$<TARGET_FILE:docksr-preview>")
    set_tests_properties(docksr-preview-cli PROPERTIES TIMEOUT 30)
    add_test(NAME docksr-preview-window COMMAND "${Python3_EXECUTABLE}"
             "${PROJECT_SOURCE_DIR}/tests/test_preview_window.py" "$<TARGET_FILE:docksr-preview>")
    set_tests_properties(docksr-preview-window PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 90)
endif()
