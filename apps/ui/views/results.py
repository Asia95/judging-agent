"""apps/ui/views/results.py — the Results tab: each eval's latest numbers, read from files."""

import streamlit as st

from evals.results import load_results

COMMANDS = """python -m evals.scenarios.run
python -m evals.judge_golden.run
python -m evals.e2e.run --runs 2
python -m evals.golden_drive.run"""


def render():
    results = [r for r in load_results() if r["model"] != "stub"]   # stub runs test the code, not the judgement
    if results:
        rows = [{
            "Evaluation": r["title"],
            "Result": " · ".join(f"{k}: {v}" for k, v in list(r["metrics"].items())[:2]),
            "Details": " · ".join(f"{k}: {v}" for k, v in list(r["metrics"].items())[2:]),
            "Judge": r["model"],
            "Prompt": r.get("prompt_version", ""),
            "Run on (UTC)": r["timestamp"][:16].replace("T", " "),
        } for r in results]
        st.dataframe(rows, hide_index=True, width="stretch", alt="The latest result of each evaluation")
    else:
        st.info("No results saved yet.", icon=":material/monitoring:")
    st.caption("This tab only reads saved results, it never starts an eval. To refresh them, from the project root:")
    st.code(COMMANDS, language="bash")
