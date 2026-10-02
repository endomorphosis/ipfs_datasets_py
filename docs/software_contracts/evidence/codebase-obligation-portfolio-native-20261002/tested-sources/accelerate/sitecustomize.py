"""Overlay sitecustomize is intentionally a no-op.

Pinning overlay task-source modules mixed nested extra-gate imports and
crashed DOEP start. Native extra-gate plus dump-stop/attach_native_lanes
owns recovery. Extra-gate uses python -P and ignores this file.
"""
