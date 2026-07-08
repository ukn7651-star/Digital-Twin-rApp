"""Save matplotlib figures as vector PDF for the paper (and optionally results/)."""

from __future__ import annotations

from pathlib import Path


def save_figure(fig, name: str, paper_dir: Path, results_dir: Path | None = None) -> Path:
    """Write ``{name}.pdf`` under ``paper_dir``; mirror to ``results_dir`` when set."""
    stem = name.removesuffix(".pdf").removesuffix(".png")
    paper_path = paper_dir / f"{stem}.pdf"
    paper_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(paper_path, format="pdf", bbox_inches="tight")
    if results_dir is not None:
        results_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(results_dir / f"{stem}.pdf", format="pdf", bbox_inches="tight")
    return paper_path


def mirror_pdf(stem: str, paper_dir: Path, results_dir: Path) -> Path | None:
    """Copy or convert a figure from ``results_dir`` into ``paper_dir`` as PDF."""
    stem = stem.removesuffix(".pdf").removesuffix(".png")
    dst = paper_dir / f"{stem}.pdf"
    src_pdf = results_dir / f"{stem}.pdf"
    if src_pdf.exists():
        import shutil
        shutil.copy2(src_pdf, dst)
        return dst
    src_png = results_dir / f"{stem}.png"
    if src_png.exists():
        _png_to_pdf(src_png, dst)
        return dst
    return None


def _png_to_pdf(png_path: Path, pdf_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    img = mpimg.imread(png_path)
    h, w = img.shape[:2]
    fig, ax = plt.subplots(figsize=(w / 130, h / 130), dpi=130)
    ax.imshow(img)
    ax.axis("off")
    fig.savefig(pdf_path, format="pdf", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
