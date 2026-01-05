import os
import re
from urllib.parse import urljoin
import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup


# =============================
# LES CONFIGURATIONS 
# =============================
st.set_page_config(page_title="Données CoinAfrique", layout="wide", page_icon="📊")

BASE = "https://sn.coinafrique.com"

CATEGORIES = {
    "Vêtements Homme": "https://sn.coinafrique.com/categorie/vetements-homme",
    "Chaussures Homme": "https://sn.coinafrique.com/categorie/chaussures-homme",
    "Vêtements Enfants": "https://sn.coinafrique.com/categorie/vetements-enfants",
    "Chaussures Enfants": "https://sn.coinafrique.com/categorie/chaussures-enfants",
}

RAW_FILES = {
    "Vêtements Homme": "data_raw/vetements_homme_raw.csv",
    "Chaussures Homme": "data_raw/chaussures_homme_raw.csv",
    "Vêtements Enfants": "data_raw/vetements_enfants_raw.csv",
    "Chaussures Enfants": "data_raw/chaussures_enfants_raw.csv",
}

KOBO_URL = "https://ee.kobotoolbox.org/x/ZsRt7EHW"
GOOGLE_URL = "https://docs.google.com/forms/d/e/1FAIpQLSdDDjxp53epBXWq0MFCalMOnP-ZZkV1K1LMI3njbTDcxGRd9Q/viewform?usp=preview"


# =============================
# STYLE CSS 
# =============================
st.markdown("""
<style>
/* Boutons Streamlit */
.stButton>button, .stDownloadButton>button {
  background: #2F80ED !important;
  color: white !important;
  border: 0 !important;
  border-radius: 12px !important;
  padding: 0.6rem 1rem !important;
  font-weight: 600 !important;
}
.stButton>button:hover, .stDownloadButton>button:hover {
  background: #2567C8 !important;
}
            
.sidebar-logo-wrap{
  display:flex;
  justify-content:center;
  align-items:center;
  margin-top: 6px;
  margin-bottom: 10px;
}
.sidebar-logo-circle{
  width:120px;
  height:120px;
  border-radius:999px;
  overflow:hidden;
  border: 3px solid rgba(255,255,255,0.12);
  box-shadow: 0 6px 20px rgba(0,0,0,0.25);
}
.sidebar-logo-circle img{
  width:100%;
  height:100%;
  object-fit:cover;
}

/* Réduit un peu l'espace du contenu sidebar */
section[data-testid="stSidebar"] .block-container {
  padding-top: 1rem;
}

</style>
""", unsafe_allow_html=True)


# =============================
# HELPERS: CLEANING (cours)
# =============================
def clean_text(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = re.sub(r"\s+", " ", str(x)).strip()
    return s if s else None

 # '10 000 CFA' -> 10000 ; 'Prix sur demande' -> None
def clean_price(raw):       
    
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or "demande" in s.lower():
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None

#  Enlève 'location_on' et normalise.
def clean_address(addr):
    
    addr = clean_text(addr)
    if not addr:
        return None
    addr = addr.replace("location_on", "").strip()
    addr = re.sub(r"\s*,\s*", ", ", addr).strip()
    return addr or None

# =============================
# HTTP SIMPLE 
# =============================
def get_html(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


# ======================================
# TAB 1: BeautifulSoup Scrapping
# ======================================
def parse_card(card: BeautifulSoup, ad_url: str) -> dict:
    # Prix 
    price_tag = card.select_one("h3, .price, [class*=price]")
    raw_price = price_tag.get_text(" ", strip=True) if price_tag else None

    # Adresse 
    addr_tag = card.select_one(".location, .address, [class*=location], [class*=address]")
    raw_addr = addr_tag.get_text(" ", strip=True) if addr_tag else None

    # fallback: 
    if not raw_addr:
        txt = card.get_text(" ", strip=True)
        if "location_on" in txt:
            raw_addr = txt

    # Image
    img = card.find("img")
    img_url = None
    if img:
        img_url = img.get("data-src") or img.get("src")
        if img_url and img_url.startswith("/"):
            img_url = urljoin(BASE, img_url)

    return {
        "prix": clean_price(raw_price),
        "adresse": clean_address(raw_addr),
        "image_lien": clean_text(img_url),
        "ad_url": clean_text(ad_url),
    }


def scrape_category_bs4(category_url: str, pages: int) -> pd.DataFrame:
    df = pd.DataFrame()
    seen = set()

    for p in range(1, int(pages) + 1):
        url = f"{category_url}?page={p}"

        try:
            html = get_html(url)
        except Exception:
            continue

        soup = BeautifulSoup(html, "lxml")
        links = soup.select('a[href^="/annonce/"]')

        data = []
        for a in links:
            try:
                href = a.get("href")
                if not href:
                    continue

                ad_url = urljoin(BASE, href)
                if ad_url in seen:
                    continue
                seen.add(ad_url)

                card = a.find_parent("div")
                if not card:
                    continue

                data.append(parse_card(card, ad_url))
            except Exception:
                pass

        DF = pd.DataFrame(data)
        df = pd.concat([df, DF], axis=0).reset_index(drop=True)

    if not df.empty:
        df = df[["prix", "adresse", "image_lien", "ad_url"]].drop_duplicates()

    return df

# =============================
# TAB 3: RAW WEB SCRAPPERS 
# =============================
def clean_raw_for_dashboard(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df.copy()

    # Supprimer colonnes techniques qui existent
    cols_to_drop = ["pagination", "_follow", "_followSelectorId", "web_scraper_order", "web_scraper_start_url"]
    df = df.drop(columns=[c for c in cols_to_drop if c in df.columns], errors="ignore")

    # Renommer colonnes 
    rename_map = {}
    for c in df.columns:
        low = c.lower()
        if "price" in low or "prix" in low:
            rename_map[c] = "prix"
        elif "address" in low or "adresse" in low or "location" in low:
            rename_map[c] = "adresse"
        elif "title" in low or "titre" in low:
            rename_map[c] = "titre"
        elif "image" in low:
            rename_map[c] = "image_lien"

    df = df.rename(columns=rename_map)

    # Nettoyage
    if "prix" in df.columns:
        df["prix"] = df["prix"].apply(clean_price)
    if "adresse" in df.columns:
        df["adresse"] = df["adresse"].apply(clean_address)
    if "titre" in df.columns:
        df["titre"] = df["titre"].apply(clean_text)
    if "image_lien" in df.columns:
        df["image_lien"] = df["image_lien"].apply(clean_text)

    # Colonnes finales 
    keep = [c for c in ["prix", "adresse", "titre", "image_lien"] if c in df.columns]
    df = df[keep].dropna(how="all").drop_duplicates()
    return df

# =============================
# HEADER 
# =============================
st.markdown("## Mini Projet: CoinAfrique")
st.markdown("<div class='small-muted'>Scraping with beautifulsoup | RAW web scraper à télécharger | Dashboard des données | Evaluation de l'app</div>",
            unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
st.divider()

# =============================
# SIDEBAR
# =============================
with st.sidebar:
    st.markdown(
        """
          <div class="sidebar-logo-circle">
            <img src="https://img.icons8.com/color/1200/web-scraper.jpg" />
          </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("## Mini Projet: CoinAfrique")
    st.caption("Collecter des données multi-pages pour scraper CoinAfrique avec BeautifulSoup, " 
               "consulter et télécharger les exports RAW Web Scraper, " 
               "nettoyer et visualiser des annonces CoinAfrique, "
               "et enfin un formulaire d'évaluation utilisateur integré (Google Forms / KoboToolbox)."
    )
    st.divider()
    st.markdown("### Sources")
    for k in CATEGORIES.values():
        st.write(f"{k}")
    st.divider()
    st.markdown("### Catégories disponibles")
    for k in CATEGORIES.keys():
        st.write(f"• {k}")

# ==============================================
# LES TABS QUI SONT LES LIENS OU ONGLETS 
# ==============================================
tab1, tab2, tab3, tab4 = st.tabs([
    "1) BeautifulSoup",
    "2) Download RAW DATA",
    "3) Dashboard",
    "4) Évaluation",
])

# =============================
# TAB 1
# =============================
with tab1:
    st.markdown("### Scraper & Nettoyer avec BeautifulSoup")
    st.caption("On scrape plusieurs pages d’une catégorie et on récupère prix, adresse, image, lien.")
    c1, c2 = st.columns([2, 1])
    with c1:
        cat_label = st.selectbox("Catégorie", list(CATEGORIES.keys()), key="tab1_cat")
    with c2:
        pages = st.number_input("Nombre de pages", min_value=1, max_value=100, value=2, step=1, key="tab1_pages")

    run = st.button("Lancer le scraping", type="primary", key="tab1_run")
    st.markdown("</div>", unsafe_allow_html=True)

    if run:
        url = CATEGORIES[cat_label]
        with st.spinner("Scraping en cours..."):
            df = scrape_category_bs4(url, pages=int(pages))

        if df.empty:
            st.warning("Aucune donnée récupérée. Essaie avec 1 page.")
        else:
            st.success(f"Terminé | {len(df)} annonces")
            st.dataframe(df, width="stretch", height=520)

# =============================
# TAB 2
# =============================
with tab2:
    # st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### RAW Web Scraper (non nettoyé)")
    st.caption("Lecture directe d’un fichier dans `.data_raw/` selon la catégorie choisie par l'utilisateur.")
    cat_raw = st.selectbox("Choisir une catégorie", list(RAW_FILES.keys()), key="tab2_cat")
    st.markdown("</div>", unsafe_allow_html=True)

    path = RAW_FILES[cat_raw]
    
    raw_df = pd.read_csv(path)
    file_name = os.path.basename(path)
    st.success(f"`Fichier {file_name} contenant {len(raw_df)} lignes chargé avec success`")

    st.dataframe(raw_df, width="stretch", height=540)

# =============================
# TAB 3
# =============================
with tab3:
    # st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Dashboard")
    st.caption("On nettoie le RAW DATA exporté via Web Scraper puis on affiche des graphiques et le tableau nettoyé de chaque categorie.")
    cat_dash = st.selectbox("Choisir une catégorie", list(RAW_FILES.keys()), key="tab3_cat")
    st.markdown("</div>", unsafe_allow_html=True)

    path = RAW_FILES[cat_dash]
    
    raw_df = pd.read_csv(path)
    clean_df = clean_raw_for_dashboard(raw_df)

    #  visualisation des graphiques et données sur carte 
    st.markdown("### Visualisations")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Annonces", len(clean_df))
    k2.metric("Prix renseignés", int(clean_df["prix"].notna().sum()) if "prix" in clean_df else 0)
    k3.metric("Prix moyen (CFA)", int(clean_df["prix"].dropna().mean()) if "prix" in clean_df and clean_df["prix"].notna().any() else 0)
    k4.metric("Localisations", int(clean_df["adresse"].notna().sum()) if "adresse" in clean_df else 0)

    g1, g2 = st.columns(2)

    # Graphe 1 : Répartition par tranche de prix
    with g1:
        st.markdown("#### Répartition par tranche de prix")
        if "prix" in clean_df.columns and clean_df["prix"].notna().any():
            bins = [0, 5000, 10000, 20000, 50000, 10**9]
            labels = ["0–5k", "5–10k", "10–20k", "20–50k", "50–100k"]
            temp = clean_df.dropna(subset=["prix"]).copy()
            temp["tranche"] = pd.cut(temp["prix"], bins=bins, labels=labels, include_lowest=True)
            tranche_counts = temp["tranche"].value_counts().reindex(labels).fillna(0).reset_index()
            tranche_counts.columns = ["tranche", "count"]
            st.bar_chart(tranche_counts.set_index("tranche"), height=250)
        else:
            st.info("Pas de prix disponibles pour tracer la répartition.")

    # Graphe 2 : Top 5 localisations
    with g2:
        st.markdown("#### Top 5 localisations")
        if "adresse" in clean_df.columns and clean_df["adresse"].notna().any():
            top_addr = clean_df["adresse"].value_counts().head(5).reset_index()
            top_addr.columns = ["adresse", "count"]
            st.bar_chart(top_addr.set_index("adresse"), height=250)
        else:
            st.info("Pas d’adresses disponibles.")

    st.markdown("### Données nettoyées")
    
    st.dataframe(clean_df, width="stretch", height=420)

# =============================
# TAB 4
# =============================
with tab4:
    st.markdown("### Évaluation de l’app")
    st.caption("Choisis un formulaire d’évaluation : KoboToolbox ou Google Forms ")
    st.markdown("</div>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### KoboToolbox")
        st.link_button("Ouvrir le formulaire Kobo", KOBO_URL)
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("#### Google Forms")
        st.link_button("Ouvrir le Google Form", GOOGLE_URL)
        st.markdown("</div>", unsafe_allow_html=True)

st.markdown("""
<style>
/* Footer */
.app-footer {         
  width: 100%;
  text-align: center;
}

/* Contenu du footer */
.app-footer .footer-box {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 0.85rem;
  color: #6b7280; 
}

/* Lien GitHub */
.app-footer a {
  color: #2F80ED;
  text-decoration: none;
  font-weight: 600;
}
.app-footer a:hover {
  text-decoration: underline;
}
</style>

<div class="app-footer">
  <div class="footer-box">
    © 2026 • Tous droits réservés •
    <a href="https://github.com/DonBos27" target="_blank">Don-Christ Bosenga Github</a> •
    Fait avec beaucoup de ❤️ et de ☕️
  </div>
</div>
""", unsafe_allow_html=True)