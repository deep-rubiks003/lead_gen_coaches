# 🏋️ Coach Lead Finder — Bright Data & SerpAPI

A powerful, customizable Python and Streamlit web application that lets you discover, verify, and harvest high-quality Instagram coach/creator accounts. It enables searching by niche (e.g. Strength training, Nutritionist, Running coach), follower range, and country, automatically verifying accounts and inferring their locations using Bright Data and SerpAPI/OpenWebNinja.

---

## 🚀 Features

* **Visual Choice Grid**: Select multiple pre-configured niche keywords or add custom keywords on the fly.
* **Target Filters**: Filter results dynamically by follower bands (e.g., 20k to 100k) and countries.
* **Verification Pipeline**:
  * Scrapes Google Search via SerpAPI or OpenWebNinja to discover potential Instagram handle profiles.
  * Hydrates handles using the **Bright Data Instagram Profiles Dataset** to ensure actual, real-time follower counts, profile names, biographies, emails, and inferred locations.
* **Local Run History**: Saves results incrementally under the `runs/` directory sorted by Country and verification status (`verified` or `discovered`), automatically deduplicating handles.
* **Direct Export**: View saved leads directly in the app and download them as CSV files.

---

## 🛠️ Prerequisites & Installation

### 1. Install Dependencies
Ensure you have **Python 3.8+** installed. Install the required libraries:

```bash
pip install streamlit pandas pyyaml httpx rich python-dotenv
```

### 2. Configure Environment Variables
Create a `.env` file in the root of the project directory:

```env
# Google SERP discovery APIs (provide at least one)
SERPAPI_KEY=your_serpapi_key_here
OPENWEBNINJA_API_KEY=your_openwebninja_key_here

# Bright Data API (for full profile validation & business data)
BRIGHTDATA_API_TOKEN=your_brightdata_token_here
BRIGHTDATA_ZONE=your_brightdata_serp_zone_here
BRIGHTDATA_IG_DATASET=gd_l1vikfch901nx3by4  # Optional: defaults to standard dataset

# Email discovery enrichment (Optional)
HUNTER_API_KEY=your_hunter_api_key_here
```

---

## 💻 Usage

### Launch the Streamlit Web Application
To run the interactive UI on `http://localhost:8501`:

```bash
streamlit run app.py
```

### Run via Command Line Interface (CLI)
You can also run searches directly from your terminal:

```bash
python simple_search.py --niches "running coach, marathon coach" --gl us --country US --min-followers 20000 --max-followers 100000 --target 100 --out leads.csv
```

---

## 📂 Project Structure

* **`app.py`**: Streamlit frontend app housing the search panels, results grids, and downloads tab.
* **`simple_search.py`**: Contains the core harvesting orchestration `harvest()` and the CLI runner.
* **`clients.py`**: HTTP API clients communicating with Bright Data (SERP and Dataset triggers), OpenWebNinja, SerpAPI, and Hunter.
* **`storage.py`**: Handles loading/saving outputs inside `runs/` with local sorting and deduplication.
* **`utils.py`**: Shared utility tools (e.g. rate limiters, regex extractors, and country inference logic).
* **`config.yaml` / `keywords.yaml`**: Pre-configured niche definitions, country code matching maps, and limits.
