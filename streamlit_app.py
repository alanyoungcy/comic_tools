from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st
from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

from comicpublish.app import main


if __name__ == "__main__":
    if get_script_run_ctx() is None:
        raise SystemExit(
            "Run this app with: streamlit run streamlit_app.py"
        )
    main()
