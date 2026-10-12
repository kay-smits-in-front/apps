# kay.apps — persoonlijk app-portaal

Deze repository bevat uitsluitend het portaal. Three Way blijft in zijn eigen repository en wordt later apart gekoppeld.

## Lokaal starten (Windows / PyCharm)

Gebruik Python 3.13:

    py -3.13 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    Copy-Item .env.example .env
    python app.py

Maak lokaal een beheerder aan. Je voert het wachtwoord interactief in; het komt niet in de code of shell-geschiedenis:

    flask --app app create-admin

De ontwikkelserver is alleen voor lokaal gebruik. Gebruik nooit `FLASK_DEBUG=1` op een publiek toegankelijke server.

## Tests uitvoeren

    python -m pytest -q

## Render: productie-infrastructuur

De root van deze repository bevat `render.yaml`, een Render Blueprint voor:
- webservice via de meegeleverde Dockerfile en Gunicorn
- PostgreSQL voor accounts
- private Redis/Key Value voor gedeelde rate limits
- regio Frankfurt
- verplichte geheime instellingen die je in Render zelf invult

### Eerste Render setup

1. Push de branch met de Render-configuratie naar GitHub.
2. Open Render en kies **New → Blueprint**; selecteer deze repository en de branch die je wilt testen.
3. Controleer de resources en eventuele kosten voordat je bevestigt. De webservice, database en Key Value hebben elk hun eigen plan/kosten; verander geen plan zonder de gevolgen voor beschikbaarheid en dataretentie te controleren.
4. Vul de gevraagde Turnstile-waarden in. Maak de site key en secret key aan in Cloudflare Turnstile; de secret key hoort uitsluitend bij Render als environment variable.
5. Vul `TRUSTED_HOSTS` in met de Render-hostnaam die Render voor de webservice heeft toegekend. Gebruik alleen hostnamen, zonder `https://`, paden of poorten.
6. Configureer SMTP-waarden als je e-mailnotificaties wilt. Zonder SMTP blijven aanvragen zichtbaar in Gebruikersbeheer, maar wordt er geen e-mail verzonden.
7. Deploy eerst als testomgeving. Controleer `/healthz`, inloggen, aanvragen, botcontrole en goedkeuring.

### Beheerder aanmaken op Render

De lokale SQLite-database en Render PostgreSQL zijn verschillende databases. Een lokaal aangemaakte admin wordt dus niet automatisch naar Render gekopieerd.

Nadat Render PostgreSQL is aangemaakt, voer je in de shell van de webservice eenmalig uit:

    flask --app app create-admin

Gebruik een sterk, uniek wachtwoord dat niet eerder in chat of in code is gedeeld. De opdracht vraagt het wachtwoord interactief en slaat alleen een hash op. Als de gekozen Render-service geen shell aanbiedt, gebruik dan een eenmalige beveiligde job/command om dezelfde CLI-opdracht uit te voeren; zet het wachtwoord nooit als vaste startopdracht of in `render.yaml`.

### Domein later koppelen

Je hoeft nu geen domein te kopen. Gebruik de toegewezen `onrender.com`-hostnaam voor een eerste stagingtest. Als je later een domein kiest, voeg je die hostnaam toe in Render, stel je de door Render opgegeven DNS-records in bij TransIP en update je `TRUSTED_HOSTS`. Gebruik de exacte hostnaam en controleer HTTPS vóór je echte privédata gebruikt.

## Security en privacy

- Formulieren gebruiken CSRF-bescherming.
- Inloggen en accountaanvragen hebben rate limits via Redis.
- Openbare aanvragen gebruiken Cloudflare Turnstile met server-side verificatie en een honeypot.
- Wachtwoorden worden gehasht; er staat geen standaard beheerderswachtwoord in de repository.
- Beheerpagina's vereisen een goedgekeurde admin met het ingestelde admin-e-mailadres.
- Productie vereist een geheime sleutel, PostgreSQL, Redis, Turnstile en expliciete toegestane hostnamen.
- Sessiecookies, CSP en securityheaders zijn ingesteld.
- `.env`, lokale databases en instance-data horen niet in Git.

Dit vermindert risico's maar garandeert geen absolute veiligheid. Voer tests, dependency-scans, back-up- en hersteltests en een handmatige security review uit voor gebruik met echte portefeuillegegevens. Gebruik MFA voor je hosting- en GitHub-account.

## Three Way

Three Way blijft volledig apart. Dit portaal bevat geen beleggingsdata en de koppeling is nog niet geïmplementeerd. Voordat anderen Three Way mogen gebruiken, moet de beleggingsapp iedere databasequery server-side beperken tot de eigenaar van de data. Alleen een verborgen link of frontendfilter is geen toegangsbeveiliging.
