---
title: Macro, tabelle e diagrammi
description: Esempi pronti delle macro di formattazione, delle tabelle dinamiche e dei diagrammi draw.io.
---

# Macro, tabelle e diagrammi

/// hero | Documentazione che si legge volentieri
    subtitle: Pannelli, card, tabelle che fanno i conti da sole e diagrammi draw.io, tutto scritto in Markdown
    color: teal
    icon: rocket

/// button | Guida completa alle macro
    link: /plugins
    color: yellow
///
///

Stato della guida: {{status: Pubblicata | green | solid}} {{status: Esempi | blue}}

## Pannelli e card

/// panel | Prima di iniziare
    color: blue
    icon: info

Ogni esempio di questa pagina si può copiare dall'editor: apri **Modifica** e guarda il sorgente.
///

//// cards
    columns: 3

/// card | Primi passi
    icon: rocket
    link: 01-primi-passi.md

Come orientarsi nel portale.
///

/// card | Organizzare i contenuti
    icon: folder
    color: orange
    link: 02-organizzare-pagine-e-cartelle.md

Cartelle, ordine del menu, pagine indice.
///

/// card | Scrivere in Markdown
    icon: note
    color: purple
    link: 03-scrivere-in-markdown.md

Riquadri, schede, checklist e diagrammi.
///
////

## Tabelle dinamiche

I dati arrivano dal file [spese-esempio.csv](spese-esempio.csv): la tabella si aggiorna da sola quando il file cambia. Clicca le intestazioni per ordinare.

/// table | Spese approvate e in attesa
    source: spese-esempio.csv
    filter: Stato <> "Respinto"
    sort: -Importo
    columns: [Data, Reparto, Voce, Importo, Stato]
    totals: [Importo]
    format: {Importo: euro}
    colors: {Stato: {Approvato: green, In attesa: yellow}}
///

/// table | Spesa per reparto
    source: spese-esempio.csv
    group: Reparto
    aggregate: ["sum(Importo) as Totale", "count(*) as Voci"]
    sort: -Totale
    format: {Totale: euro}
    chart: hbar
///

## Diagrammi draw.io

/// drawio | schema-rete.drawio
    caption: Rete di sede (2 pagine, usa le frecce per la seconda)
///

## Citare altre pagine

/// include | 03-scrivere-in-markdown.md#checklist
///

## Tutte le pagine di questa sezione

/// pages | .
    style: cards
///
