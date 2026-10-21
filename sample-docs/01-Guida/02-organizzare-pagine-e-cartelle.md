# Organizzare pagine e cartelle

Ogni **cartella** diventa una sezione del menu e può contenere pagine, file e altre cartelle.

## Creare velocemente

Apri il pannello **Nuovo** in uno di questi modi:

- il pulsante **Nuovo** in cima al menu, oppure il tasto ++n++ da qualsiasi pagina;
- il **+** che compare passando sopra una cartella del menu: crea direttamente lì dentro;
- **Nuovo** nella pagina di una cartella.

La cartella di destinazione proposta è quella in cui ti trovi; puoi cambiarla dal menu **Dentro**.

=== "Pagina"

    Scrivi il titolo e premi ++enter++: la pagina viene creata e si apre nell'editor.

    Usa `/` per creare anche le cartelle che mancano, in un colpo solo:

    ```text
    Procedure/Qualità/Controllo accessi
    ```

    crea le cartelle *Procedure* e *Qualità* (se non esistono) e la pagina *Controllo accessi*.
    Con ++shift+enter++ (o **Crea e continua**) la pagina viene creata e il pannello resta aperto per la successiva.

=== "Cartella"

    Scrivi il nome della cartella; anche qui `/` crea più livelli (`Manuali/Software`).
    Lascia spuntato **Crea anche la pagina della cartella** per avere subito una pagina introduttiva (`index.md`).

=== "Struttura"

    Per preparare un'intera sezione scrivi un elemento per riga e usa il rientro per indicare cosa sta dentro cosa:

    ```text
    Procedure/
      Qualità/
        Controllo accessi
        Non conformità
      Gestione resi
    Glossario
    ```

    - Le righe che finiscono con `/`, o che hanno righe rientrate sotto, diventano **cartelle**; le altre **pagine**.
    - Puoi incollare un elenco puntato da un altro documento.
    - ++tab++ e ++shift+tab++ cambiano il rientro delle righe selezionate; ++ctrl+enter++ crea.
    - Le cartelle e le pagine che esistono già vengono lasciate come sono.

## Nomi e ordine

- Il **titolo** che scrivi diventa il titolo della pagina (`# Titolo`); il nome del file viene ricavato da solo, senza accenti né spazi (`controllo-accessi.md`).
- Un **prefisso numerico** decide l'ordine nel menu e non viene mostrato: `01 Introduzione`, `02 Installazione`… diventano `01-introduzione.md`, `02-installazione.md`, con titolo *Introduzione*, *Installazione*.
- Le cartelle mantengono il nome che scrivi (anche `02-Procedure`: nel menu appare *Procedure*).
- Se una cartella ha un `index.md`, cliccando sul suo nome nel menu si apre quella pagina.

## Allegati

Nella pagina di una cartella, **Carica file** aggiunge PDF, presentazioni, fogli di calcolo, documenti Word e immagini: ognuno compare nel menu con la sua icona. Dall'editor puoi anche trascinare un file nel testo per caricarlo e inserire il link.

## Spostare, rinominare, eliminare

Dal menu **⋯** di una pagina, di un file o di una cartella. Spostando una cartella si spostano anche i permessi definiti al suo interno.
