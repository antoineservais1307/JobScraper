import asyncio
import sys
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict
from playwright.async_api import async_playwright


@dataclass
class JobSearchParams:
    """
    Stocke et formate l'ensemble des critères de recherche pour générer l'URL LinkedIn.
    """
    keyword: str
    location: str
    allow_remote: bool
    experience_levels: List[str]  # Codes LinkedIn : '2'=Débutant, '3'=Confirmé, etc.
    required_keywords: List[str]
    date_posted_range: str = "r604800"  # 'r86400'=24h, 'r604800'=1 semaine, 'r2592000'=1 mois
    max_jobs: int = 20

    def build_linkedin_url(self) -> str:
        """
        Construit l'URL de recherche publique avec tous les paramètres HTTP nécessaires.
        """
        kw_encoded = self.keyword.replace(" ", "%20")
        loc_encoded = self.location.replace(" ", "%20")
        url = f"https://www.linkedin.com/jobs/search/?keywords={kw_encoded}&location={loc_encoded}"

        # Exclut les stages en ciblant uniquement le temps plein (CDI / CDD)
        url += "&f_JT=F"

        # Niveau d'expérience
        if self.experience_levels:
            exp_str = ",".join(self.experience_levels)
            url += f"&f_E={exp_str}"

        # Télétravail / Hybride (2 = Remote, 3 = Hybrid)
        if self.allow_remote:
            url += "&f_WT=2,3"

        # Date de publication
        if self.date_posted_range:
            url += f"&f_TPR={self.date_posted_range}"

        return url


def prompt_user_criteria() -> JobSearchParams:
    """
    Pose les questions dans le terminal, affiche un récapitulatif et demande confirmation.
    """
    print("=" * 60)
    print("      CONFIGURATEUR DE RECHERCHE D'EMPLOI INTERACTIF")
    print("=" * 60)

    keyword = input("➔ Intitulé du poste (ex: Data Analyst) : ").strip()
    location = input("➔ Localisation (ex: Paris) : ").strip()

    # Télétravail
    remote_input = input("➔ Acceptez-vous le télétravail / hybride ? (o/n) [o] : ").strip().lower()
    allow_remote = remote_input in ["o", "oui", "y", "yes", ""]

    # Expérience
    print("\n[Niveau d'expérience demandé]")
    print(" 1. Premier emploi / Débutant (0-2 ans)")
    print(" 2. Confirmé (1-3 ans / Associate)")
    print(" 3. Les deux")
    exp_choice = input("➔ Choix (1/2/3) [3] : ").strip()

    if exp_choice == "1":
        experience_levels = ["2"]
    elif exp_choice == "2":
        experience_levels = ["3"]
    else:
        experience_levels = ["2", "3"]

    # Date de publication
    print("\n[Ancienneté de publication max]")
    print(" 1. Dernières 24 heures")
    print(" 2. Dernière semaine")
    print(" 3. Dernier mois")
    date_choice = input("➔ Choix (1/2/3) [2] : ").strip()

    if date_choice == "1":
        date_range = "r86400"
        date_label = "Dernières 24 heures"
    elif date_choice == "3":
        date_range = "r2592000"
        date_label = "Dernier mois"
    else:
        date_range = "r604800"
        date_label = "Dernière semaine"

    # Mots-clés / Compétences
    keywords_input = input("\n➔ Mots-clés/Compétences recherchés séparés par des virgules (ex: Python, SQL, Excel, Power BI) : ").strip()
    required_keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]

    # Limite du nombre d'offres
    max_jobs_input = input("➔ Nombre max d'offres à récupérer [20] : ").strip()
    max_jobs = int(max_jobs_input) if max_jobs_input.isdigit() else 20

    params = JobSearchParams(
        keyword=keyword,
        location=location,
        allow_remote=allow_remote,
        experience_levels=experience_levels,
        required_keywords=required_keywords,
        date_posted_range=date_range,
        max_jobs=max_jobs
    )

    # Récapitulatif
    print("\n" + "-" * 60)
    print("RÉCAPITULATIF DE VOTRE RECHERCHE :")
    print(f" • Poste              : {params.keyword}")
    print(f" • Lieu               : {params.location}")
    print(f" • Télétravail/Hybride: {'Oui' if params.allow_remote else 'Non'}")
    print(f" • Expérience         : {', '.join(params.experience_levels)} (Codes LinkedIn)")
    print(f" • Ancienneté max     : {date_label}")
    print(f" • Compétences        : {', '.join(params.required_keywords) if params.required_keywords else 'Aucune restriction'}")
    print(f" • Offres max         : {params.max_jobs}")
    print(f" • URL générée        : {params.build_linkedin_url()}")
    print("-" * 60)

    confirm = input("\n➔ Lancer le scraping avec ces critères ? (o/n) [o] : ").strip().lower()
    if confirm not in ["o", "oui", "y", "yes", ""]:
        print("Opération annulée.")
        sys.exit(0)

    return params


class LinkedInScraper:
    """
    Gère la navigation avec Playwright et l'extraction des données.
    """
    def __init__(self, params: JobSearchParams):
        self.params = params

    async def scrape(self) -> List[Dict[str, str]]:
        url = self.params.build_linkedin_url()
        jobs_data = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            print("\n[Playwright] Lancement du navigateur et chargement de la page...")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            print("[Playwright] Chargement dynamique des offres...")
            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            cards = await page.query_selector_all(".base-card")
            print(f"[Playwright] Cartes trouvées sur la page : {len(cards)}\n")

            for card in cards:
                if len(jobs_data) >= self.params.max_jobs:
                    break

                try:
                    # Extraction des données
                    title_elem = await card.query_selector(".base-search-card__title")
                    title = (await title_elem.inner_text()).strip() if title_elem else "N/A"

                    company_elem = await card.query_selector(".base-search-card__subtitle")
                    company = (await company_elem.inner_text()).strip() if company_elem else "N/A"

                    loc_elem = await card.query_selector(".job-search-card__location")
                    location = (await loc_elem.inner_text()).strip() if loc_elem else "N/A"

                    link_elem = await card.query_selector("a.base-card__full-link")
                    link = await link_elem.get_attribute("href") if link_elem else "N/A"
                    clean_link = link.split("?")[0] if link != "N/A" else "N/A"

                    snippet_elem = await card.query_selector(".job-search-card__snippet")
                    snippet_text = (await snippet_elem.inner_text()).lower() if snippet_elem else ""

                    # Détection des mots-clés dans le titre et l'aperçu
                    full_text = f"{title} {snippet_text}".lower()
                    matched_keywords = [
                        kw for kw in self.params.required_keywords if kw.lower() in full_text
                    ]

                    job_entry = {
                        "Intitulé": title,
                        "Entreprise": company,
                        "Localisation": location,
                        "Mots-clés trouvés": ", ".join(matched_keywords) if matched_keywords else "Aucun détecté",
                        "Lien": clean_link
                    }
                    jobs_data.append(job_entry)

                    # --- Affichage direct dans le terminal ---
                    print("-" * 60)
                    print(f"✅ Offre #{len(jobs_data)} extraite")
                    print(f" 💼 Poste      : {title}")
                    print(f" 🏢 Entreprise : {company}")
                    print(f" 📍 Lieu       : {location}")
                    print(f" 🔑 Mots-clés  : {job_entry['Mots-clés trouvés']}")
                    
                    # Pause pour faciliter la lecture en direct
                    await asyncio.sleep(0.4)

                except Exception as e:
                    continue

            await browser.close()

        return jobs_data


def save_to_csv(data: List[Dict[str, str]], filename: str = "offres_linkedin.csv") -> None:
    """
    Exporte les données en CSV avec séparateur ';' et encodage UTF-8 avec BOM (compatible Excel).
    """
    if not data:
        print("\nAucune donnée à enregistrer.")
        return

    df = pd.DataFrame(data)
    # sep=";" force la séparation en vraies colonnes dans Excel en français
    df.to_csv(filename, index=False, sep=";", encoding="utf-8-sig")
    print("\n" + "=" * 60)
    print(f"🎉 SUCCÈS : {len(data)} offres enregistrées dans '{filename}'.")
    print("=" * 60)


async def main():
    # 1. Questionnaire interactif
    params = prompt_user_criteria()

    # 2. Scraping des données
    scraper = LinkedInScraper(params)
    results = await scraper.scrape()

    # 3. Export CSV
    save_to_csv(results, filename="offres_linkedin.csv")


if __name__ == "__main__":
    asyncio.run(main())