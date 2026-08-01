# The pybind11 extension. Off by default; scikit-build-core turns it on via
# cmake.define.HELPMATE_PYTHON in the root pyproject.toml.
if(HELPMATE_PYTHON)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(_helpmate pymodule.cpp)
  target_link_libraries(_helpmate PRIVATE helpmate_core)
  install(TARGETS _helpmate DESTINATION helpmate)
endif()
