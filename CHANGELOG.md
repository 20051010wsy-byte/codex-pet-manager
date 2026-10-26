# Changelog

## v1.0.3

- Fixed the header subtitle overlapping the top of the Mini & Pets library panel at 125% DPI.
- Added an explicit 104 px header row height so title and subtitle remain inside the header.
- Rechecked text bounds and panel positions at 1080, 1280, and 1440 pixel window widths.

## v1.0.2

- Fixed the center preview collapsing when the side panels requested wider text layouts.
- Fixed side panel widths to 320 px and 356 px so the preview receives the remaining space.
- Moved the version footer into the normal layout flow.
- Added wrapping and truncation for long names, descriptions, IDs, and program text.
- Verified layout at 1080, 1280, and 1440 pixel window widths without clipped controls.

## v1.0.1

- Fixed mouse wheel scrolling being disabled when the pointer moved between scroll panels.
- Added pointer-based wheel routing through child controls.
- Fixed high-resolution touchpad deltas being rounded to zero.
- Added wheel direction and delta bounds tests.

## v1.0.0

- Initial Windows desktop pet manager release.
- Added local Mini & Pets scanning, animated previews, import, enable/disable, rename, and delete.
- Added BailongPet and dsh-pet process controls.
