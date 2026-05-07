#pragma once

#include <cstdarg>
#include <cstdio>

inline int printf_stderr(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  int result = std::vfprintf(stderr, fmt, args);
  va_end(args);
  return result;
}
