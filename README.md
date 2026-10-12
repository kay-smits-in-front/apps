# kay.apps — persoonlijk app-portaal

Deze repository bevat uitsluitend het portaal. Three Way blijft in zijn eigen repository en wordt later veilig gekoppeld.

## Lokaal starten (Windows / PyCharm)

    py -3.13 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    Copy-Item .env.example .env
    python app.py

Maak een beheerder aan. Het wachtwoord wordt interactief gevraagd en staat niet in code:

    flask --app app create-admin

## Productieconfiguratie

De app weigert op te starten als verplichte productie-instellingen ontbreken. Stel deze in als environment variables bij de hostingprovider, niet in HTML/CSS/JavaScript, niet in Git en niet in een URL:

- APP_ENV=production
- FLASK_DEBUG=0
- SECRET_KEY: minimaal 32 willekeurige tekens, uniek voor productie
- ADMIN_EMAIL=kaysmits@icloud.com
- DATABASE_URL: PostgreSQL-connection string van de hostingprovider
- TRUSTED_HOSTS: exacte domeinen, kommagescheiden, bijvoorbeeld apps.jouwdomein.nl
- RATELIMIT_STORAGE_URI: Redis-URL (redis:// of rediss://) voor gedeelde rate limits
- TURNSTILE_SITE_KEY en TURNSTILE_SECRET_KEY: Cloudflare Turnstile keys; server-side verificatie is verplicht voor openbare accountaanvragen
- TRUSTED_PROXY_HOPS: alleen instellen op het exacte aantal vertrouwde reverse proxies als de hostingprovider dat vereist

Optioneel voor e-mailmeldingen:
- MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM

SMTP ontbreekt? Dan wordt de aanvraag nog opgeslagen en zichtbaar onder Gebruikersbeheer, maar komt er geen e-mailmelding. Configureer SMTP voordat je op e-mailmeldingen vertrouwt.

## Server en domein

De applicatie draait in productie via Gunicorn, niet via Flask' development server. Gebruik de meegeleverde Dockerfile of start met:

    gunicorn --workers 2 --threads 4 --timeout 30 --bind 0.0.0.0:$PORT wsgi:app

Gebruik een hostingprovider met persistente PostgreSQL, Redis, environment variables en automatische HTTPS.

Een domeinnaam plak je niet in Python. Voeg de domeinnaam toe in het dashboard van je hostingprovider. De host toont daarna de DNS-instructies; voeg die bij TransIP toe als A/AAAA- of CNAME-record zoals de host voorschrijft. Voeg vervolgens exact die hostnaam toe aan TRUSTED_HOSTS. Wacht op DNS-propagatie en controleer HTTPS voordat je privégegevens gebruikt.

## Beveiliging in deze basis

- CSRF-bescherming op formulieren
- Rate limits op inloggen en aanvragen, met Redis in productie
- Cloudflare Turnstile server-side verificatie en honeypot tegen bots
- Wachtwoorden alleen als hash opgeslagen
- Admin-routes vereisen een ingelogde, goedgekeurde beheerder met het ingestelde admin-e-mailadres
- Beveiligde sessiecookies, CSP en security response headers
- Productie start niet zonder expliciete secret-, PostgreSQL-, Redis- en Turnstile-configuratie
- Geen wachtwoorden of geheime sleutels in frontend-output of repository

## Voor livegang verplicht

Dit is een geharde basis, geen garantie op absolute veiligheid. Stel alle secrets in bij de host, configureer HTTPS/DNS, maak versleutelde back-ups en test herstel, voer dependency/security scans uit, en test login, rate limits, CSRF, accountgoedkeuring en autorisatie. Schakel MFA in voor het beheerder-account waar mogelijk. Voor delen met andere gebruikers moet Three Way eerst per gebruiker geïsoleerde portefeuilledata afdwingen.

## Three Way

Three Way blijft zelfstandig. Deze portal bevat nog geen beleggingsdata en deelt niets met andere gebruikers. Koppel Three Way pas nadat authenticatie, autorisatie en data-isolatie daar ook server-side zijn gecontroleerd.
