add_library(docksr_core profile_registry.cpp frame_scheduler.cpp json.cpp)
target_sources(docksr_core PRIVATE status_snapshot.cpp schedule_simulation.cpp)
target_include_directories(docksr_core PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_compile_features(docksr_core PUBLIC cxx_std_20)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(docksr_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_library(docksr_inference_worker inference_worker.cpp)
target_link_libraries(docksr_inference_worker PUBLIC docksr_core)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(docksr_inference_worker PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_CLI)
  add_executable(docksr-mock mock_main.cpp)
  target_link_libraries(docksr-mock PRIVATE docksr_core)
  if(UNIX)
    # Host-reference experiment; Python/ORT are invoked only when explicitly run.
    add_executable(docksr-worker-reference worker_reference_main.cpp)
    target_link_libraries(docksr-worker-reference PRIVATE docksr_inference_worker)
  endif()
endif()

if(BUILD_TESTING)
  add_executable(docksr-inference-worker-tests ${PROJECT_SOURCE_DIR}/tests/inference_worker_tests.cpp)
  target_link_libraries(docksr-inference-worker-tests PRIVATE docksr_inference_worker)
  add_test(NAME inference_worker_contract COMMAND docksr-inference-worker-tests)
  add_test(NAME inference_worker_schema
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tests/test_inference_worker_schema.py"
            "$<TARGET_FILE:docksr-inference-worker-tests>"
            "${PROJECT_SOURCE_DIR}/schemas/inference-worker.schema.json")
  add_executable(docksr-core-tests ${PROJECT_SOURCE_DIR}/tests/core_tests.cpp)
  target_link_libraries(docksr-core-tests PRIVATE docksr_core)
  add_test(NAME docksr-core COMMAND docksr-core-tests)
  add_executable(docksr-schedule-tests ${PROJECT_SOURCE_DIR}/tests/schedule_tests.cpp)
  target_link_libraries(docksr-schedule-tests PRIVATE docksr_core)
  add_test(NAME docksr-schedule COMMAND docksr-schedule-tests)
  if(BUILD_CLI)
    add_test(NAME docksr-schedule-cli
             COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tests/test_schedule_cli.py"
                     "$<TARGET_FILE:docksr-mock>")
    add_test(NAME docksr-mock-default COMMAND docksr-mock)
    foreach(docksr_scenario IN ITEMS normal late late-consumer crash resize suspend exhaustion stale)
      add_test(NAME docksr-mock-${docksr_scenario}
               COMMAND docksr-mock --enable --scenario ${docksr_scenario})
    endforeach()
  endif()
  find_package(Threads REQUIRED)
  add_executable(docksr-status-tests ${PROJECT_SOURCE_DIR}/tests/status_tests.cpp)
  target_link_libraries(docksr-status-tests PRIVATE docksr_core Threads::Threads)
  add_test(NAME docksr-status COMMAND docksr-status-tests)
endif()
