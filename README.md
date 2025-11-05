# privategripp

## Exporttool voor relaties met geaccordeerde offertes en opdrachten

Gebruik het script `export_relations_with_sales.py` om gegevens uit Gripp te
combineren. Het script ondersteunt twee modi:

1. **CSV-modus** – werk met bestaande exports voor relaties, offertes en
   opdrachten.
2. **API-modus** – laat het script zelf alle gegevens ophalen via de Gripp API
   zodat je een geautomatiseerde, reproduceerbare export krijgt.

### CSV-modus

```bash
python export_relations_with_sales.py \
  --relations relaties.csv \
  --offers offertes.csv \
  --assignments opdrachten.csv \
  --output relaties_met_sales.csv
```

De output bevat alle kolommen uit het relatiesbestand plus aanvullende kolommen:

* `Aantal geaccordeerde offertes`
* `Offerte-ID's`
* `Aantal opdrachten`
* `Opdracht-ID's`

Gebruik `--accepted-status` om extra offerte-statussen toe te voegen die als
geaccordeerd tellen.

### Snelstart (alleen API)

1. **Installeer afhankelijkheden**

   ```bash
   python -m pip install -r requirements.txt
   ```

2. **Zet je API-token klaar**

   ```bash
   export GRIPP_API_TOKEN="plak_hier_je_token"
   ```

3. **Doorloop de wizard** – deze haalt voorbeelden op en stelt kolomnamen
   voor. Kies `j` om de export te starten wanneer de samenvatting klopt.

   ```bash
   python export_relations_with_sales.py --output relaties_met_sales.csv --wizard \
     --offers-filter status=Geaccordeerd --assignments-filter status=Actief
   ```

4. **Draai de export opnieuw zonder wizard (optioneel)** voor een volledig
   geautomatiseerde run, bijvoorbeeld in een cronjob of workflow.

   ```bash
   python export_relations_with_sales.py --output relaties_met_sales.csv \
     --relations-id-field id --offer-relation-field relation_id --offer-id-field id \
     --offer-status-field status --assignment-relation-field relation_id \
     --assignment-id-field id --offers-filter status=Geaccordeerd \
     --assignments-filter status=Actief
   ```

   Het bestand `relaties_met_sales.csv` verschijnt in dezelfde map als het
   script en bevat alleen relaties die zowel een geaccordeerde offerte als een
   opdracht hebben.

### API-modus

1. Vraag in Gripp een API-token aan (Beheer → Instellingen → API). Sla dit op in
   de omgeving, bijvoorbeeld `export GRIPP_API_TOKEN=...`.
2. Kies of je de interactieve **wizard** wilt gebruiken. Met `--wizard` haalt het
   script voorbeeldrecords op en stelt het kolomnamen voor op basis van de
   daadwerkelijke API-respons.
3. Voer het script uit en geef alleen het uitvoerbestand op. De standaard
   API-functies `relations.list`, `offers.list` en `assignments.list` worden
   aangeroepen.

```bash
python export_relations_with_sales.py \
  --output relaties_met_sales.csv \
  --wizard
```

Handige opties:

* `--api-token` – overschrijft `GRIPP_API_TOKEN`.
* `--api-base-url` – gebruik een alternatieve API-URL (bijvoorbeeld voor een
  sandbox).
* `--relations-function`, `--offers-function`, `--assignments-function` – geef
  eigen functienamen door wanneer je de standaard endpoints wilt aanpassen.
* `--api-filter KEY=VALUE` – stuur extra parameters naar alle API-aanroepen,
  bijvoorbeeld `--api-filter status=Actief`.
* `--relations-filter`, `--offers-filter`, `--assignments-filter` – filters per
  type, handig om offertes bijvoorbeeld direct te beperken tot
  `status=Geaccordeerd`.
* `--relations-data-path`, `--offers-data-path`, `--assignments-data-path` –
  stel in waar in de JSON-respons de lijsten staan (bijv. `data.items`).
* `--limit-param` en `--offset-param` – pas aan als de API andere
  pagineringsparameters gebruikt (zoals `page` i.p.v. `offset`).
* `--wizard` – begeleidt je door het kiezen van kolomnamen en JSON-paden op
  basis van live API-voorbeelden.

Je kunt CSV- en API-modus ook combineren; wanneer voor een onderdeel een CSV-pad
is opgegeven, heeft dat voorrang. Zo kun je bijvoorbeeld relaties lokaal
leveren en de bijbehorende offertes via de API ophalen.

#### Stap-voor-stap voorbeeld met alleen de API

```bash
export GRIPP_API_TOKEN=...              # 1. token klaarzetten

# 2. Laat de wizard de API verkennen en kolomnamen voorstellen
python export_relations_with_sales.py \
  --output relaties_met_sales.csv \
  --wizard \
  --offers-filter status=Geaccordeerd \
  --assignments-filter status=Actief

# 3. Voer eventueel nogmaals uit zonder wizard voor een geautomatiseerde run
python export_relations_with_sales.py \
  --output relaties_met_sales.csv \
  --relations-id-field id \
  --offer-relation-field relation_id \
  --offer-id-field id \
  --offer-status-field status \
  --assignment-relation-field relation_id \
  --assignment-id-field id \
  --offers-filter status=Geaccordeerd \
  --assignments-filter status=Actief
```

*De wizard toont een samenvatting van je keuzes. Controleer deze en draai daarna
een tweede, geautomatiseerde run zonder `--wizard` als je het proces wilt
scripted uitvoeren.*

### Afhankelijkheden

Het script gebruikt alleen standaardbibliotheken plus `requests`. Installeer de
benodigde packages bij voorkeur via `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

### Problemen oplossen

* Controleer het logniveau met `--log-level DEBUG` voor meer details bij API- en
  CSV-fouten.
* Als de API onverwachte structuren terugstuurt, verschijnt een duidelijke
  foutmelding met de eerste tekens van de respons. Gebruik dit samen met de
  officiële documentatie (<https://api.gripp.com/public/api3.php>) om het juiste
  functienaam en parameters te bepalen.
