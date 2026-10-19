# KLM — DJI Tello workspace

KLM is de voorbereidende projectmap voor een DJI/Ryze Tello-drone-app binnen de privéportal `apps`.

## Status

**Alleen structuur en dashboard.** Er is nog geen drone-controlcode, Wi-Fi-socket, cameraverwerking, modelintegratie of vluchtactie geïmplementeerd.

## Beoogde structuur

- `connection/` — toekomstige Wi-Fi- en Tello SDK-verbinding
- `vision/` — toekomstige cameraframes, gezichtsdetectie en gebarenherkenning
- `mapping/` — toekomstige indoor kaartopbouw en ruimtelijke representatie
- `ai/` — toekomstige LangChain-integratie en model-/toolroutering
- `safety/` — toekomstige vluchtlimieten, noodstop en handmatige overname
- `docs/` — architectuur en beslissingen

De map bevat voorlopig alleen README-bestanden zodat de grenzen tussen onderdelen vastliggen zonder al functies te programmeren.

## Ontwerpnotities

De Tello SDK gebruikt Wi-Fi en UDP voor commando's, status en video. De concrete ondersteuning hangt af van het exacte Tello-model en de SDK-versie. De webportal is het dashboard; vluchtbesturing en realtime beeldverwerking horen later in een lokale Python-worker op de computer die met de drone-Wi-Fi verbonden is, niet in een gehoste webworker.

AI mag later alleen voorstellen doen; een aparte veiligheidslaag moet vluchtcommando's begrenzen. Volgen, naderen of iemand aantikken wordt niet automatisch ingeschakeld. Voor veilig indoor gebruik moet de app rekening houden met mensen, huisdieren, muren, propellerbescherming en een directe handmatige stop.
