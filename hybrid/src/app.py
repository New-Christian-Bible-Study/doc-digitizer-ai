from pathlib import Path
import shutil
import tempfile
import time
import subprocess
import sys

import fitz  # PyMuPDF
import streamlit as st
import os
from dotenv import load_dotenv

from pdf_tools.extract_pdf_page_range import extract_page_range
from pdf_tools.split_double_page_pdf import split_double_page_pdf

import paddle_pipe
import gemini_pipe


# ---------------------------------------------------------------------
# Language Options
# ---------------------------------------------------------------------

LANGUAGE_OPTIONS = {
    "Abaza": "abq",
    "Afrikaans": "af",
    "Albanian": "sq",
    "Arabic": "ar",
    "Avaric": "ava",
    "Azerbaijani": "az",
    "Belarusian": "be",
    "Bhojpuri": "bho",
    "Bihari": "bh",
    "Bosnian": "bs",
    "Bulgarian": "bg",
    "Chechen": "che",
    "Chinese (Simplified)": "ch",
    "Chinese (Traditional)": "chinese_cht",
    "Croatian": "hr",
    "Czech": "cs",
    "Danish": "da",
    "Dargwa": "dar",
    "Dutch": "nl",
    "English": "en",
    "Estonian": "et",
    "French": "fr",
    "Georgian": "ka",
    "German": "de",
    "Haryanvi": "bgc",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Icelandic": "is",
    "Indonesian": "id",
    "Ingush": "inh",
    "Irish": "ga",
    "Italian": "it",
    "Japanese": "japan",
    "Kabardian": "kbd",
    "Konkani": "gom",
    "Korean": "korean",
    "Kurdish": "ku",
    "Lak": "lbe",
    "Latin": "la",
    "Latvian": "lv",
    "Lezghian": "lez",
    "Lithuanian": "lt",
    "Magahi": "mah",
    "Maithili": "mai",
    "Malay": "ms",
    "Maltese": "mt",
    "Maori": "mi",
    "Marathi": "mr",
    "Mongolian": "mn",
    "Nepali": "ne",
    "Newari": "new",
    "Norwegian": "no",
    "Occitan": "oc",
    "Old English": "ang",
    "Pali": "pi",
    "Persian": "fa",
    "Polish": "pl",
    "Portuguese": "pt",
    "Romanian": "ro",
    "Russian": "ru",
    "Sadri": "sck",
    "Sanskrit": "sa",
    "Serbian (Cyrillic)": "rs_cyrillic",
    "Serbian (Latin)": "rs_latin",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Spanish": "es",
    "Swahili": "sw",
    "Swedish": "sv",
    "Tabassaran": "tab",
    "Tagalog": "tl",
    "Tamil": "ta",
    "Telugu": "te",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Urdu": "ur",
    "Uyghur": "ug",
    "Uzbek": "uz",
    "Vietnamese": "vi",
    "Welsh": "cy"
}

# ---------------------------------------------------------------------
# Folder roots
# ---------------------------------------------------------------------

WORK_ROOT = Path("work")
OUTPUT_ROOT = Path("output")


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".webp",
    }


def make_job_dir(uploaded_name: str) -> Path:
    stem = Path(uploaded_name).stem
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    job_dir = WORK_ROOT / f"{stem}_{timestamp}"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def save_uploaded_file(uploaded_file, job_dir: Path) -> Path:
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    input_path = input_dir / uploaded_file.name
    input_path.write_bytes(uploaded_file.getbuffer())

    return input_path


def prepare_pdf_for_pipeline(
    input_pdf: Path,
    pipeline_pdf: Path,
    do_extract: bool,
    page_range: str,
    do_split: bool,
    split_ratio: float,
    rtl: bool,
) -> Path:

    pipeline_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        current_pdf = input_pdf

        if do_extract:
            extracted_pdf = tmp_dir / "extracted.pdf"

            extract_page_range(
                input_pdf=current_pdf,
                output_pdf=extracted_pdf,
                page_range=page_range,
            )

            current_pdf = extracted_pdf

        if do_split:
            split_double_page_pdf(
                input_pdf=current_pdf,
                output_pdf=pipeline_pdf,
                split_ratio=split_ratio,
                rtl=rtl,
            )

            return pipeline_pdf

        shutil.copyfile(current_pdf, pipeline_pdf)
        return pipeline_pdf


def prepare_image_for_pipeline(input_image: Path, pipeline_image: Path) -> Path:
    """
    Images do not need PDF preprocessing.
    Copy the uploaded image into the pipeline input folder.
    """

    pipeline_image.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_image, pipeline_image)
    return pipeline_image


def input_to_page_images(input_path: Path, job_dir: Path, dpi: int = 300) -> list[Path]:

    pages_dir = job_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Clear old page images if rerunning.
    for old_file in pages_dir.glob("*"):
        if old_file.is_file():
            old_file.unlink()

    if is_pdf(input_path):
        doc = fitz.open(input_path)

        page_paths = []
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out_path = pages_dir / f"page_{i:03d}.png"
            pix.save(out_path)
            page_paths.append(out_path)

        doc.close()
        return page_paths

    if is_image(input_path):
        out_path = pages_dir / "page_001.png"
        shutil.copyfile(input_path, out_path)
        return [out_path]

    raise ValueError(f"Unsupported pipeline input type: {input_path}")



def run_paddle_page_reference(page_image: Path, job_dir: Path, lang: str) -> Path:

    paddle_dir = job_dir / "paddle"
    paddle_dir.mkdir(parents=True, exist_ok=True)

    out_json = paddle_dir / f"{page_image.stem}.json"

    out_json = paddle_pipe.run_paddle_page(image_path=page_image, output_json=out_json, lang=lang)

    st.write(f"📄 PaddleOCR page image: `{page_image}`")
    st.write(f"📝 Paddle JSON: `{out_json}`")

    return out_json



def extract_info_page_reference(paddle_json: Path, job_dir: Path) -> Path:

    payload_dir = job_dir / "gemini_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)

    out_payload = payload_dir / paddle_json.name

    st.write(f"📦 Extract compact Gemini payload from: `{paddle_json}`")
    st.write(f"📦 Payload JSON: `{out_payload}`")

    return gemini_pipe.make_gemini_payload_file(paddle_json, out_payload)


def run_gemini_page_reference(page_image: Path, payload_json: Path, job_dir: Path) -> Path:

    gemini_dir = job_dir / "gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)

    out_json = gemini_dir / payload_json.name

    st.write(f"🤖 Send to Gemini image: `{page_image}`")
    st.write(f"🤖 Send to Gemini payload: `{payload_json}`")
    st.write(f"🤖 Gemini response: `{out_json}`")

    return gemini_pipe.run_gemini_page(
        image_path=page_image,
        payload_json=payload_json,
        output_json=out_json,
    )


def merge_page_reference(paddle_json: Path, gemini_json: Path, job_dir: Path) -> Path:

    merged_dir = job_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    out_json = merged_dir / paddle_json.name

    st.write(f"🔀 Merge Paddle JSON: `{paddle_json}`")
    st.write(f"🔀 Merge Gemini JSON: `{gemini_json}`")
    st.write(f"🔀 Merged JSON: `{out_json}`")

    return gemini_pipe.merge_gemini_into_paddle_file(
        paddle_json=paddle_json,
        gemini_json=gemini_json,
        output_json=out_json,
    )


def open_editor_reference(job_dir: Path) -> None:
    st.write(f"✏️ Opening editor for job: `{job_dir}`")
    
    # Launches the Tkinter editor as an independent window
    # Make sure your editor file is named 'editor.py' in the same folder
    editor_script = Path(__file__).parent / "editor.py"
    subprocess.Popen([sys.executable, str(editor_script), str(job_dir)])


def run_pipeline_reference(pipeline_input: Path, job_dir: Path, dpi: int, lang: str) -> None:
    """
    Page-based pipeline:

        pipeline_input PDF/image
        -> page images
        -> PaddleOCR per page
        -> compact Gemini payload per page
        -> Gemini per page
        -> merge per page
        -> editor over full job
    """

    with st.status("Running OCR pipeline...", expanded=True) as status:
        st.write("### 0. Converting input to page images")

        page_images = input_to_page_images(
            input_path=pipeline_input,
            job_dir=job_dir,
            dpi=dpi,
        )

        st.write(f"Created `{len(page_images)}` page image(s).")

        merged_outputs = []

        for idx, page_image in enumerate(page_images, start=1):
            st.write("---")
            st.write(f"### Processing page {idx}/{len(page_images)}: `{page_image.name}`")

            st.write("#### 1. PaddleOCR")
            paddle_json = run_paddle_page_reference(page_image, job_dir, lang)

            st.write("#### 2. Extract compact Gemini payload")
            payload_json = extract_info_page_reference(paddle_json, job_dir)

            st.write("#### 3. Gemini OCR")
            gemini_json = run_gemini_page_reference(page_image, payload_json, job_dir)

            st.write("#### 4. Merge Gemini response into Paddle JSON")
            merged_json = merge_page_reference(paddle_json, gemini_json, job_dir)

            merged_outputs.append(merged_json)

        st.write("---")
        st.write("### 5. Open editor")
        open_editor_reference(job_dir)

        status.update(label="Pipeline finished", state="complete")

    st.success("Pipeline finished.")
    st.write("Merged outputs:")
    for path in merged_outputs:
        st.write(f"- `{path}`")


# ---------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="NCBS OCR Pipeline",
        layout="centered",
    )

    st.title("NCBS OCR Pipeline")
    st.caption(
        "Upload a PDF or image, optionally preprocess the PDF, then run "
        "PaddleOCR → Gemini → merge → editor."
    )

    uploaded_file = st.file_uploader(
        "Upload PDF or image",
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"],
    )

    if not uploaded_file:
        st.stop()

    if "job_dir" not in st.session_state:
        st.session_state.job_dir = make_job_dir(uploaded_file.name)

    job_dir = Path(st.session_state.job_dir)
    input_path = save_uploaded_file(uploaded_file, job_dir)

    st.success(f"Uploaded: {uploaded_file.name}")
    st.caption(f"Job folder: `{job_dir}`")

    pipeline_input_dir = job_dir / "pipeline_input"
    pipeline_input_dir.mkdir(parents=True, exist_ok=True)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        dpi = st.number_input(
            "PDF render DPI",
            min_value=100,
            max_value=600,
            value=300,
            step=50,
            help="Used when converting PDF pages to images for OCR.",
        )
    with col2:
        lang_names = sorted(list(LANGUAGE_OPTIONS.keys()))
        default_idx = lang_names.index("English") if "English" in lang_names else 0
        selected_lang_name = st.selectbox(
            "OCR Language",
            options=lang_names,
            index=default_idx,
            help="Language model passed into PaddleOCR."
        )
        selected_lang_code = LANGUAGE_OPTIONS[selected_lang_name]

    st.divider()

    # ----------------------------------------------------------
    # Image path
    # ----------------------------------------------------------

    if is_image(input_path):
        st.subheader("Image input")
        st.image(str(input_path), caption="Uploaded image", use_container_width=True)

        pipeline_input = pipeline_input_dir / input_path.name

        if st.button("Prepare image and run pipeline", type="primary"):
            prepared_input = prepare_image_for_pipeline(
                input_image=input_path,
                pipeline_image=pipeline_input,
            )

            st.success(f"Prepared pipeline image: `{prepared_input}`")
            run_pipeline_reference(prepared_input, job_dir, dpi=dpi, lang=selected_lang_code)

        st.stop()

    # ----------------------------------------------------------
    # PDF path
    # ----------------------------------------------------------

    if not is_pdf(input_path):
        st.error("Unsupported file type.")
        st.stop()

    st.subheader("PDF preprocessing")

    do_extract = st.checkbox("Extract page range")

    page_range = ""
    if do_extract:
        page_range = st.text_input(
            "Page range",
            value="1-1",
            help="Use 1-based pages, e.g. 1-10 or 7.",
        )

    do_split = st.checkbox("Split double-page spreads")

    split_ratio = 0.5
    rtl = False

    if do_split:
        split_ratio = st.slider(
            "Split ratio",
            min_value=0.30,
            max_value=0.70,
            value=0.50,
            step=0.01,
            help="0.5 splits exactly down the middle.",
        )

        rtl = st.checkbox(
            "Right-to-left page order",
            help="Useful for RTL books: output right half before left half.",
        )

    st.divider()

    pipeline_pdf = pipeline_input_dir / f"{input_path.stem}_pipeline.pdf"

    if st.button("Prepare PDF and run pipeline", type="primary"):
        if do_extract and not page_range.strip():
            st.error("Please enter a page range.")
            st.stop()

        try:
            prepared_input = prepare_pdf_for_pipeline(
                input_pdf=input_path,
                pipeline_pdf=pipeline_pdf,
                do_extract=do_extract,
                page_range=page_range,
                do_split=do_split,
                split_ratio=split_ratio,
                rtl=rtl,
            )

            st.success(f"Prepared pipeline PDF: `{prepared_input}`")
            run_pipeline_reference(prepared_input, job_dir, dpi=dpi, lang=selected_lang_code)

        except Exception as e:
            st.error(f"Failed: {e}")


if __name__ == "__main__":
    main()