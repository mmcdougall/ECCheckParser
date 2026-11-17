# FAB FY 2025/26-2026/27 work-plan variants

This directory preserves two official-source copies of the Financial Advisory
Board work plan adopted January 28, 2025. They are kept separately because the
City Council packet incorporates two typo corrections that are absent from the
standalone ArchiveCenter PDF.

## ArchiveCenter standalone

`fab-work-plan-archivecenter-7932.pdf` is an exact, byte-for-byte copy of the
City's standalone ArchiveCenter item 7932.

- Official listing: `FY 2025/2026 - 2026/2027 Workplan`
- Source URL: https://www.elcerrito.gov/ArchiveCenter/ViewFile/Item/7932
- Canonical source file:
  `data/originals/financial-advisory-board/2025/work-plans/2025-01-28 Work Plan.pdf`
- PDF pages: 17
- Size: 204,238 bytes
- SHA-256: `d468d2e4a589939a2a55dfc9da0fc69b611628f275f0c501578c08879ac0d7c5`
- Preservation: no page, content, or metadata changes

The server filename `Work Plan-Accomplishments 2025-2027 x.pdf` and a separately
supplied download both have the same SHA-256 value. Despite that filename, this
PDF is the work plan rather than a later accomplishments update.

## Derived City Council packet extraction

`fab-work-plan-city-council-packet.pdf` contains pages 27-43 from the revised
March 4, 2025 City Council agenda packet. It is a derived extraction from an
official source, not a separately published standalone City file. The 17 source
pages were copied into a standalone PDF without changing their page content,
media boxes, or rotation. Descriptive PDF metadata was added to identify the
extraction.

- Source packet:
  `data/originals/city-council/2025/agenda-packets/2025-03-04 Agenda Packet.pdf`
- Official packet name: `Agenda Packet (rev. 3.5.2025)`
- CivicClerk file ID: `2304`
- Published at: `2025-03-05T14:49:47.337Z`
- Source URL:
  https://elcerritoca.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=2304,plainText=false)
- Agenda bill: PDF pages 25-26 transmit the adopted FAB work plan to the City
  Council as a receive-and-file item.
- Source page range: PDF pages 27-43, corresponding to work-plan pages 1-17
- Source packet SHA-256:
  `8843b27b389a6901cfceae5c9e4b6b59b3ed3d7ea774305aae23133bcfa951e7`
- Extracted PDF size: 1,852,071 bytes
- Extracted PDF SHA-256:
  `084d24c268951e8f3272918224ab23a96a4c51b203e0a43d787eb810152df7a5`
- Extracted at: `2026-08-26T00:20:54Z`
- Extraction tool: `pypdf 6.10.0`

## Known relationship and anomalies

- On internal page 8, the ArchiveCenter PDF reads `Mondy Market Secur`; the
  City Council packet reads `Money Market Secure`. These are the two typo
  corrections recorded in the FAB's January 28 adoption motion.
- The adoption motion is preserved in
  `data/originals/financial-advisory-board/2025/agenda-packets/2025-02-25 Agenda Packet.pdf`,
  PDF page 19.
- No other substantive wording difference was found. The Council copy includes
  its agenda-packet page footer and has different PDF object structure because
  it was extracted from the packet.
- Both copies record the January 28, 2025 adoption and vote on page 17.
- Both copies retain the source-authored sentence `This document is superceded
  by the FY25-27 document` on page 1, even though the document is itself the
  FY 2025/26-2026/27 work plan. The archive preserves that wording unchanged.

For quotations or analysis where the corrected wording matters, prefer the City
Council packet copy. Use the ArchiveCenter copy when exact reproduction of the
standalone published file is required.
