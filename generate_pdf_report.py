import os
import re
import base64
import subprocess
from pathlib import Path

def main():
    base_dir = Path(__file__).resolve().parent
    template_html = base_dir / "GridNest_Technical_Structure_Report.html"
    compiled_html = base_dir / "GridNest_Technical_Structure_Report_compiled.html"
    output_pdf = base_dir / "GridNest_Technical_Structure_Report.pdf"
    img_path = base_dir / "frontend" / "static" / "assets" / "ml_accuracy_curves.png"

    print("Encoding image to Base64...")
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    print("Reading HTML template...")
    with open(template_html, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace("__IMG_B64__", f"data:image/png;base64,{img_b64}")

    print("Writing compiled HTML...")
    with open(compiled_html, "w", encoding="utf-8") as f:
        f.write(content)

    print("Compiling PDF with Google Chrome Headless...")
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    cmd = [
        chrome_path,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={str(output_pdf)}",
        str(compiled_html)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        print("Stdout:", res.stdout)
    if res.stderr:
        print("Stderr:", res.stderr)

    if output_pdf.exists():
        size = output_pdf.stat().st_size
        print(f"Generated PDF successfully: {output_pdf} ({size:,} bytes)")
        
        with open(output_pdf, "rb") as f:
            pdf_bytes = f.read()
        pages = len(re.findall(rb'/Type\s*/Page\b', pdf_bytes))
        print(f"Verified PDF Page Count: {pages}")
        if pages == 6:
            print("PERFECT: Document is exactly 6 pages as requested!")
        else:
            print(f"Page count note: {pages} pages detected.")
    else:
        print("ERROR: Failed to generate PDF.")

if __name__ == "__main__":
    main()
