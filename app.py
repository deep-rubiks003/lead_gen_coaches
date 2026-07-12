"""Streamlit UI for the coach/creator lead harvester (SerpAPI).

Run:  streamlit run app.py
Inputs: coach type, follower range, country. Output: table + CSV download.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import storage
from simple_search import harvest

st.set_page_config(page_title="Coach Lead Finder", page_icon="🏋️", layout="wide")


st.title("🏋️ Coach Lead Finder — Bright Data")
st.caption("Find Instagram coach/creator accounts by niche, follower range, and "
           "country — powered by Bright Data SERP.")

_saved = storage.list_countries()
page = st.radio(
    "view",
    [f"🔍 Search", f"📂 Saved Leads ({sum(c['verified'] for c in _saved)})"],
    horizontal=True, label_visibility="collapsed")


def render_saved_page() -> None:
    saved = storage.list_countries()
    if not saved:
        st.info("No saved leads yet — run a search first.")
        return
    opts = [f"{c['flag']} {c['country']}  ·  {c['verified']} verified / "
            f"{c['discovered']} discovered" for c in saved]
    c1, c2 = st.columns([3, 2])
    pick = c1.selectbox("Country", opts, key="sv_country")
    ccode = saved[opts.index(pick)]["country"]
    kind = c2.radio("Show", ["verified", "discovered"], horizontal=True,
                    key="sv_kind")
    files = storage.list_keyword_files(ccode, kind)
    if not files:
        st.info(f"No {kind} data saved for {ccode} yet.")
        return
    st.caption(f"{ccode} · {kind} — {len(files)} keyword file(s). Tables shown "
               f"directly below.")
    import csv as _csv
    for kf in files:
        st.markdown(f"#### {kf['keyword']}  ·  {kf['count']} leads")
        with open(kf["path"], encoding="utf-8") as fh:
            df = pd.DataFrame(list(_csv.DictReader(fh)))
        st.dataframe(
            df, width="stretch", hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("profile"),
                "followers": st.column_config.NumberColumn(format="%d"),
            })
        st.download_button(
            f"⬇️ Download {kf['filename']}", kf["csv_bytes"],
            file_name=kf["filename"], mime="text/csv",
            key=f"sv_dl_{ccode}_{kind}_{kf['filename']}")
        st.divider()


if page.startswith("📂"):
    render_saved_page()
    st.stop()

# country -> (gl code, label)
COUNTRIES = {
    "United States": ("us", "US"), "Canada": ("ca", "CA"),
    "United Kingdom": ("uk", "UK"), "Australia": ("au", "AU"),
    "New Zealand": ("nz", "NZ"), "South Africa": ("za", "ZA"),
    "India": ("in", "IN"), "Ireland": ("ie", "IE"),
    # GCC
    "Saudi Arabia": ("sa", "SA"), "United Arab Emirates": ("ae", "AE"),
    "Qatar": ("qa", "QA"), "Kuwait": ("kw", "KW"),
    "Bahrain": ("bh", "BH"), "Oman": ("om", "OM"),
}

# Coach types + keywords are loaded from keywords.yaml (edit there, no code
# change needed). Falls back to a minimal built-in set if the file is missing.
from pathlib import Path

import yaml


@st.cache_data
def load_keywords() -> dict[str, list[str]]:
    path = Path(__file__).parent / "keywords.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {k: list(v) for k, v in data.items() if v}
    return {"Fitness coach": ["fitness coach", "online fitness coach"]}


COACH_KEYWORDS = load_keywords()

# ---------------- Step 1: pick coach types (cards grid) ----------------
ICONS = {
    "Strength training coach": "🏋️", "Nutritionist": "🥗",
    "Fitness coach": "💪", "Transformation coach": "✨",
    "Weight loss coach": "⚖️", "Running coach": "🏃",
}

st.subheader("1 · Choose coach types")
if "sel_types" not in st.session_state:
    st.session_state.sel_types = {next(iter(COACH_KEYWORDS), "")}

types = list(COACH_KEYWORDS.keys())
NCOLS = 3
for start in range(0, len(types), NCOLS):
    cols = st.columns(NCOLS)
    for col, ctype in zip(cols, types[start:start + NCOLS]):
        with col:
            sel = ctype in st.session_state.sel_types
            with st.container(border=True):
                st.markdown(f"## {ICONS.get(ctype, '🎯')}")
                st.markdown(f"**{ctype}**")
                st.caption(f"{len(COACH_KEYWORDS[ctype])} keywords")
                if st.button("✓ Selected" if sel else "Select",
                             key=f"card_{ctype}",
                             type="primary" if sel else "secondary",
                             use_container_width=True):
                    st.session_state.sel_types.discard(ctype) if sel \
                        else st.session_state.sel_types.add(ctype)
                    st.rerun()

chosen_types = [t for t in types if t in st.session_state.sel_types]

# ---------------- Step 2: refine keywords (pills) ----------------
selected_niches: list[str] = []
if chosen_types:
    st.subheader("2 · Keywords to search")
    st.caption("Tap a keyword to toggle it. All on by default — each selected "
               "keyword runs as its own search.")
    for ctype in chosen_types:
        kws = COACH_KEYWORDS[ctype]
        with st.container(border=True):
            st.markdown(f"**{ICONS.get(ctype, '🎯')} {ctype}**")
            picked = st.pills(
                ctype, kws, selection_mode="multi", default=kws,
                key=f"kw_{ctype}", label_visibility="collapsed")
            selected_niches += (picked or [])

custom = st.text_input(
    "➕ Add custom keywords (comma-separated)",
    placeholder="e.g. yoga coach, pilates instructor",
    help="One-off niches not in the lists above. Each becomes its own search.")
if custom:
    selected_niches += [c.strip() for c in custom.split(",") if c.strip()]
selected_niches = list(dict.fromkeys(selected_niches))   # dedupe, keep order

if selected_niches:
    st.info(f"**{len(selected_niches)} keyword(s)** will be searched: "
            + ", ".join(selected_niches))

st.divider()

# ---------------- Step 3: target settings ----------------
st.subheader("3 · Target")
c1, c2 = st.columns(2)
with c1:
    country_name = st.selectbox(
        "Country", list(COUNTRIES.keys()) + ["🌍 Custom…"],
        help="Pick 'Custom…' to type any country — it will be injected into "
             "the search query as text.")
    if country_name == "🌍 Custom…":
        country_name = st.text_input(
            "Custom country", placeholder="e.g. Singapore, Germany, Nigeria")
    city = st.text_input(
        "City (optional)", placeholder="e.g. Dubai, Mumbai, London",
        help="Added to the search query as text to bias results to this city.")
    target = st.number_input("Max results", 10, 500, 100, step=10)
with c2:
    fol = st.slider("Follower range", 0, 2_000_000, (20_000, 100_000),
                    step=5_000, format="%d")

verify = st.checkbox(
    "✅ Verify followers + location (Bright Data) — guarantees real follower "
    "counts and infers country. Slower (~1–5 min).", value=True)

with st.expander("Advanced options"):
    pages = st.slider("Pages per query", 1, 10, 5)
    geo_in_query = st.checkbox(
        "Inject country name into the search (biases discovery to that "
        "country; drops snippet counts — fine under Verify).", value=False)
    no_filter = st.checkbox("No follower filter (snippet-only mode)",
                            value=False)
    strict_country = st.checkbox(
        "Keep only accounts whose inferred country matches (verify mode)",
        value=False)

go = st.button("🔍 Find leads", type="primary", use_container_width=True)

if go:
    niches = selected_niches
    if not niches:
        st.error("Pick at least one coach type or add a custom keyword.")
        st.stop()
    coach_type = ", ".join(niches)
    country_name = (country_name or "").strip()
    if not country_name:
        st.error("Enter a custom country (or pick one from the list).")
        st.stop()
    is_custom = country_name not in COUNTRIES
    if is_custom:
        # no Google region code for free-text countries -> default gl, and
        # force the name into the query so it actually biases discovery.
        gl = "us"
        label = country_name.upper().replace(" ", "_")[:20]
    else:
        gl, label = COUNTRIES[country_name]
    lo, hi = fol
    # discovery: inject country NAME (and city) into the query as plain text
    geo_bits = []
    if geo_in_query or is_custom:
        geo_bits.append(country_name)
    if city.strip():
        geo_bits.append(city.strip())
    geo_term = " ".join(geo_bits)
    nf = no_filter or bool(geo_term)   # geo-in-query loses counts -> no filter
    # strict country match only works for known ISO codes (infer_country
    # returns codes from config.yaml) — skip it for custom free-text countries.
    fc = label if (verify and strict_country and not is_custom) else None

    status = st.empty()
    prog = st.progress(0.0)
    found: list[str] = []

    def cb(msg: str) -> None:
        if msg.startswith("+ @"):
            found.append(msg)
            prog.progress(min(len(found) / float(target), 1.0))
        status.write(msg)

    with st.spinner(f"Searching {country_name} for '{coach_type}'…"):
        result = harvest(niches, lo, hi, target=int(target), gl=gl,
                         country=label, geo_term=geo_term, no_filter=nf,
                         pages=pages, out=None, verify=verify, filter_country=fc,
                         progress=cb)

    prog.progress(1.0)
    discovered = result["discovered"]
    final = result["final"]

    # persist this run into per-country / per-keyword history (non-blocking).
    # verified + discovered stored separately under runs/<country>/<kind>/.
    try:
        nv = storage.save_results(final, label, kind="verified")
        nd = storage.save_results(discovered, label, kind="discovered")
        if nv or nd:
            st.toast(f"Saved {nv} verified + {nd} discovered to {label} 📁")
    except Exception as e:  # noqa: BLE001
        st.warning(f"Could not save to history: {e}")

    cols = ["handle", "name", "followers", "niche", "country", "url", "bio"]

    def _table(rows, label_txt, fname):
        if not rows:
            st.info(f"No rows for {label_txt}.")
            return
        df = pd.DataFrame(rows)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
        st.dataframe(
            df, width="stretch", hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("profile"),
                "followers": st.column_config.NumberColumn(format="%d"),
            })
        st.download_button(
            f"⬇️ Download {label_txt} CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=fname, mime="text/csv", key=fname)

    if not discovered:
        st.warning("No accounts found. Try a wider follower range, more niche "
                   "terms, or enable 'No follower filter'.")
    elif verify:
        # two outputs: raw discovery (pre-verify) + verified
        st.success(f"Discovered {len(discovered)} accounts → "
                   f"{len(final)} verified in band + country")
        t1, t2 = st.tabs([f"✅ Verified ({len(final)})",
                          f"📋 Discovered / pre-verify ({len(discovered)})"])
        with t1:
            _table(final, "verified", f"leads_{label}_{lo}_{hi}_verified.csv")
        with t2:
            st.caption("Every handle found (real Bright Data followers, but "
                       "NOT filtered by band/country). 0 = profile not "
                       "returned by Bright Data.")
            _table(discovered, "discovered",
                   f"leads_{label}_{lo}_{hi}_discovered.csv")
    else:
        st.success(f"Found {len(final)} accounts")
        _table(final, "results", f"leads_{label}_{lo}_{hi}.csv")
