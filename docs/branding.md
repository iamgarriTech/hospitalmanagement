# VitaCore brand assets

Product name: **VitaCore**, matching the supplied wordmark. Tagline: **Healthier people. Brighter tomorrows.** Hospital organizations and facilities keep their own names inside the workspace.

The source artwork is held by the project owner and is deliberately not in the repository — it is a working file rather than a deliverable, and the exported masters below are what the application uses. Transparent PNG masters were prepared using the built-in imagegen editing tool from this reference; these are raster adaptations, not a vector master or a lossless crop of the original.

## Files

All downloadable assets are in `frontend/public/brand/`. Open `/brand/index.html` in the running app to preview and download the complete set.

| File | Use |
| --- | --- |
| `vitacore-icon.png` | 512 px symbol without text; collapsed navigation and loading screen |
| `vitacore-icon-{32,64,128,192}.png` | Small icon exports |
| `vitacore-wordmark.png` | Standalone navy/indigo wordmark on light backgrounds |
| `vitacore-wordmark-light.png` | Standalone lavender wordmark on dark backgrounds |
| `vitacore-horizontal.png` | Symbol and wordmark; sidebar and mobile header |
| `vitacore-horizontal-light.png` | Symbol and lavender wordmark; dark login panel |
| `vitacore-stacked.png` | Vertical logo for covers and presentations |
| `vitacore-stacked-light.png` | Vertical logo for dark backgrounds |

`frontend/src/app/favicon.ico`, `icon.png`, and `apple-icon.png` provide browser and home-screen icons through Next.js file conventions. The Apple icon intentionally has a white background; the other PNG brand exports preserve transparency.

The shared `BrandLogo` component selects full, light, or icon-only presentation. The original tagline appears on the login panel. Page metadata identifies the product as VitaCore.

## Rebuild derived assets

From `frontend/`, run `node scripts/build-brand-assets.mjs` after replacing the approved icon or wordmark master. The script uses Sharp (installed with Next.js) to create sizes and layouts, and reuses the primary wordmark's alpha channel for the light export. Both wordmarks therefore have identical outlines and spacing.

Use the original 512 px symbol and 1200 px wordmark masters without stretching. Leave clear space around the logo. Do not use the stacked version in compact navigation or set the tagline at unreadable sizes.

## Imagegen prompt record

Tool mode: built-in imagegen; no fallback API or CLI was used. The accepted master prompts were:

- **Symbol:** “Extract just the exact purple medical-cross symbol with central human/leaf motif from the provided source logo. No wordmark, no tagline. Preserve the cross outline, circular head, two leaves, and all original ribbon gradients. Truly transparent alpha background outside and inside the cross around the central person. Clean crisp antialiased boundaries. Center the complete icon with 6 percent breathing room on a square canvas.”
- **Wordmark:** “Extract only the original VitaCore wordmark from the supplied logo as a tightly cropped wide transparent PNG. Exact text VitaCore, uppercase V and C and lowercase other letters. Preserve the original bold geometric letterforms and kerning, dark navy Vita, indigo Core. Remove the medical cross symbol and remove the complete tagline. Remove off-white background to real alpha including letter counters. No redesign, no new text.”

Generated reverse-wordmark attempts did not preserve real transparency and were rejected. The final lavender reverse is derived from the accepted transparent wordmark's existing alpha rather than those rejected files.
