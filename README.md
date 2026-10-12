# Apps — persoonlijk app-platform

Een privé startpunt voor eigen tools. Deze repository bevat het **portaal**; losse apps zoals **Three Way** blijven in hun eigen repositories en worden later gekoppeld.

## Techniek
- Python 3.13+
- Flask backend met server-rendered Jinja templates
- Responsive CSS-interface voor telefoon en desktop
- SQLite voor lokaal ontwikkelen

## Eerste versie
- Inlogpagina en afgeschermd dashboard
- Accountaanvragen blijven pending totdat de beheerder ze goedkeurt
- Gebruikersbeheer uitsluitend voor `kaysmits@icloud.com`
- Three Way staat als placeholder in het dashboard; de code is niet gekopieerd of aangepast in deze repository

## Lokaal starten in PyCharm (Windows)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Maak daarna een beheerdersaccount aan met het interactieve commando:

```powershell
flask --app app create-admin
```

Dit stelt het account `kaysmits@icloud.com` in als goedgekeurde beheerder en vraagt interactief om een wachtwoord. Gebruik een uniek wachtwoord van minimaal 12 tekens. Open daarna http://127.0.0.1:5000.

## Veiligheid vóór online zetten
- Houd deze GitHub-repository privé.
- Zet nooit `.env`, databases, DEGIRO-exports of andere privégegevens in Git.
- Vervang `SECRET_KEY` in `.env` door een lange willekeurige geheime waarde.
- De account-aanvraagpagina is nog een basisversie: er is CSRF-bescherming, maar e-mailverificatie, rate limiting en aanvullende anti-botmaatregelen moeten nog worden toegevoegd vóór openbare registratie.
- Gebruik in productie HTTPS, secure cookies, een production WSGI-server, een persistente database en backups.
- Voor meerdere gebruikers is PostgreSQL een betere productiedatabase dan lokale SQLite.

## Later: Three Way koppelen
Three Way blijft zelfstandig in de eigen repository. We kunnen later kiezen voor een beveiligde link naar een apart gehoste instantie of een integratie achter geauthenticeerde routes. Voordat meerdere gebruikers toegang krijgen, moeten we expliciet vastleggen dat iedere gebruiker alleen eigen portefeuilledata kan zien.
