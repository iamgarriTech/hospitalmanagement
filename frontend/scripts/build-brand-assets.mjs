import sharp from 'sharp'
import { writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

// Rebuild layout and size variants from the approved transparent PNG masters.
const brand = fileURLToPath(new URL('../public/brand/', import.meta.url))
const app = fileURLToPath(new URL('../src/app/', import.meta.url))
const transparent = { r: 0, g: 0, b: 0, alpha: 0 }
const icon = `${brand}vitacore-icon.png`

// Reuse the approved wordmark's alpha for the reverse export so both variants
// have identical letterforms, spacing, and antialiasing.
const wordmarkMaster = `${brand}vitacore-wordmark.png`
const masterSize = await sharp(wordmarkMaster).metadata()
const wordmarkAlpha = await sharp(wordmarkMaster).extractChannel('alpha').toBuffer()
await sharp({
  create: {
    width: masterSize.width,
    height: masterSize.height,
    channels: 3,
    background: '#b8b5ff',
  },
})
  .joinChannel(wordmarkAlpha)
  .png()
  .toFile(`${brand}vitacore-wordmark-light.png`)

for (const suffix of ['', '-light']) {
  const wordmark = `${brand}vitacore-wordmark${suffix}.png`
  const mark = await sharp(icon).resize(256, 256).toBuffer()
  const word = await sharp(wordmark).resize({ width: 768 }).toBuffer({ resolveWithObject: true })
  await sharp({ create: { width: 1088, height: 256, channels: 4, background: transparent } })
    .composite([
      { input: mark, left: 0, top: 0 },
      { input: word.data, left: 288, top: Math.round((256 - word.info.height) / 2) },
    ])
    .png()
    .toFile(`${brand}vitacore-horizontal${suffix}.png`)

  const stackedWord = await sharp(wordmark)
    .resize({ width: 960 })
    .toBuffer({ resolveWithObject: true })
  await sharp({ create: { width: 1088, height: 768, channels: 4, background: transparent } })
    .composite([
      { input: await sharp(icon).resize(512, 512).toBuffer(), left: 288, top: 16 },
      { input: stackedWord.data, left: 64, top: 568 },
    ])
    .png()
    .toFile(`${brand}vitacore-stacked${suffix}.png`)
}

for (const size of [32, 64, 128, 192]) {
  await sharp(icon).resize(size, size).png().toFile(`${brand}vitacore-icon-${size}.png`)
}
await sharp(icon).resize(64, 64).png().toFile(`${app}icon.png`)
await sharp(icon)
  .resize(180, 180)
  .flatten({ background: '#ffffff' })
  .png()
  .toFile(`${app}apple-icon.png`)

// ICO with an embedded PNG frame, supported by modern browsers.
const png = await sharp(icon).resize(32, 32).png().toBuffer()
const header = Buffer.alloc(22)
header.writeUInt16LE(1, 2)
header.writeUInt16LE(1, 4)
header[6] = 32
header[7] = 32
header.writeUInt16LE(1, 10)
header.writeUInt16LE(32, 12)
header.writeUInt32LE(png.length, 14)
header.writeUInt32LE(22, 18)
await writeFile(`${app}favicon.ico`, Buffer.concat([header, png]))
console.log('Built VitaCore horizontal, stacked, favicon, and home-screen variants.')
