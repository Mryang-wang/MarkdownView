param(
    [string]$Artwork = "$PSScriptRoot\..\design\app-icon\artwork-v1.1.2.png"
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$iconAssemblies = @([System.Drawing.Image].Assembly.Location,
    [System.Drawing.Point].Assembly.Location, 'System.Runtime', 'System.Collections')
foreach ($assemblyName in @('System.Private.Windows.GdiPlus.dll', 'System.Private.Windows.Core.dll')) {
    $drawingAssembly = Join-Path ([IO.Path]::GetDirectoryName([System.Drawing.Image].Assembly.Location)) $assemblyName
    if (Test-Path -LiteralPath $drawingAssembly) { $iconAssemblies += $drawingAssembly }
}
Add-Type -ReferencedAssemblies $iconAssemblies -TypeDefinition @'
using System;
using System.IO;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class MarkdownViewIconExport {
    static Bitmap Resize(Image source, int size) {
        var result = new Bitmap(size, size, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(result)) {
            g.CompositingMode = CompositingMode.SourceCopy;
            g.CompositingQuality = CompositingQuality.HighQuality;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            using (var attrs = new ImageAttributes()) {
                attrs.SetWrapMode(WrapMode.TileFlipXY);
                g.DrawImage(source, new Rectangle(0, 0, size, size), 0, 0,
                    source.Width, source.Height, GraphicsUnit.Pixel, attrs);
            }
        }
        return result;
    }

    // Canonical rounded-square alpha for Windows: keep the generated artwork
    // intact inside the tile and exclude any matte fringe outside its boundary.
    static Bitmap Normalize(Image artwork) {
        const int size = 1024;
        var result = new Bitmap(size, size, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(result)) {
            g.Clear(Color.White);
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.DrawImage(artwork, new Rectangle(0, 0, size, size));
        }
        using (var mask = new Bitmap(size, size, PixelFormat.Format32bppArgb)) {
            using (var g = Graphics.FromImage(mask))
            using (var shape = new GraphicsPath()) {
                g.Clear(Color.Transparent);
                g.SmoothingMode = SmoothingMode.AntiAlias;
                float inset = size * .012f, diameter = size * .39f;
                float edge = size - inset;
                shape.AddArc(inset, inset, diameter, diameter, 180, 90);
                shape.AddArc(edge - diameter, inset, diameter, diameter, 270, 90);
                shape.AddArc(edge - diameter, edge - diameter, diameter, diameter, 0, 90);
                shape.AddArc(inset, edge - diameter, diameter, diameter, 90, 90);
                shape.CloseFigure();
                g.FillPath(Brushes.White, shape);
            }
            var rect = new Rectangle(0, 0, size, size);
            var pixels = result.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
            var alpha = mask.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try {
                var row = new byte[size * 4]; var maskRow = new byte[size * 4];
                for (int y = 0; y < size; y++) {
                    var address = IntPtr.Add(pixels.Scan0, y * pixels.Stride);
                    Marshal.Copy(address, row, 0, row.Length);
                    Marshal.Copy(IntPtr.Add(alpha.Scan0, y * alpha.Stride), maskRow, 0, maskRow.Length);
                    for (int x = 0; x < size; x++) {
                        int offset = x * 4;
                        row[offset + 3] = maskRow[offset + 3];
                        if (row[offset + 3] == 0) { row[offset] = row[offset + 1] = row[offset + 2] = 0; }
                    }
                    Marshal.Copy(row, 0, address, row.Length);
                }
            } finally { result.UnlockBits(pixels); mask.UnlockBits(alpha); }
        }
        return result;
    }

    public static void Export(string artworkPath, string pngPath, string icoPath, string sizesDir) {
        Directory.CreateDirectory(sizesDir);
        int[] sizes = {16, 20, 24, 32, 40, 48, 64, 96, 128, 256};
        var frames = new List<byte[]>();
        using (var artwork = Image.FromFile(artworkPath))
        using (var normalized = Normalize(artwork)) {
            normalized.Save(pngPath, ImageFormat.Png);
            foreach (int size in sizes) {
                using (var frame = Resize(normalized, size))
                using (var memory = new MemoryStream()) {
                    frame.Save(memory, ImageFormat.Png);
                    frames.Add(memory.ToArray());
                    frame.Save(Path.Combine(sizesDir, "icon-" + size + ".png"), ImageFormat.Png);
                }
            }
        }
        using (var writer = new BinaryWriter(File.Create(icoPath))) {
            writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
            int offset = 6 + sizes.Length * 16;
            for (int i = 0; i < sizes.Length; i++) {
                writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                writer.Write((byte)0); writer.Write((byte)0);
                writer.Write((ushort)1); writer.Write((ushort)32);
                writer.Write(frames[i].Length); writer.Write(offset);
                offset += frames[i].Length;
            }
            foreach (var frame in frames) { writer.Write(frame); }
        }
    }
}
'@
$iconRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourcePath = (Resolve-Path -LiteralPath $Artwork).Path
[MarkdownViewIconExport]::Export($sourcePath, (Join-Path $iconRoot '图片1.png'),
    (Join-Path $iconRoot '图片1.ico'), (Join-Path $iconRoot 'design\app-icon\sizes'))
Write-Output 'Exported square PNG and 10 Windows ICO sizes: 16, 20, 24, 32, 40, 48, 64, 96, 128, 256.'
