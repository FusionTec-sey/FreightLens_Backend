# Connected Vendor Network — Future Scope

Status: future scope, nothing built. Not scheduled — kept here to be developed later.
Living copy: https://claude.ai/code/artifact/8eb3fa40-348d-47d3-9e6e-c88e90fb2f1a (edits there do not flow back; re-export to refresh this file).
Companion: the supplier master-data plan review — https://claude.ai/code/artifact/a0cad4cd-e5a9-4f6e-81e9-0a7b8b9e6f76

2026-10-14 · @PArth

A concept note for linking FreightLens tenants so that a buyer and a vendor who both run the system exchange requisitions and quotes directly, instead of by email. Written from the concept as described, refined into something buildable.

## The concept, refined

Today a vendor is a row in your supplier table. You write an RFQ, send it out of the system, and someone types the reply back in. The vendor has no account, no visibility, and no obligation — the record of what they said is whatever your buyer entered.

The proposal is that a vendor who also runs FreightLens stops being a row and becomes **a counterparty**: a separate organisation, with its own tenant and its own data, connected to yours by mutual consent. An RFQ you send arrives in their system as work to do. The quote they write arrives in yours as a quote already structured, already attached to the right lines, with no retyping and no dispute about what was said.

Three things follow from that, and they are what make this different from a feature:

**They are not part of your group.** A linked vendor is an independent tenant — an individual company or a group of their own. Your organisation hierarchy, your shared-supplier rules and your permissions do not extend to them. The link is a relationship between two sovereign tenants, not a branch of your org tree.

**Linking is consented, by code.** They generate a connection code and give it to you out of band. You enter it. Nothing is exposed until both sides have acted. The code proves the vendor meant to connect with you specifically.

**What you see is what they chose to share.** You receive the organisation information they publish to partners — legal name, country, contacts, certificates — not their database. Whether you then treat that linked supplier as shared across your group or private to one company remains entirely your internal affair, exactly as it is today.

The missing piece on your side is small but load-bearing: **an RFQ currently has no vendor selection at all**, only dates. Adding "who is this going to" is the hinge the whole concept turns on, and it is worth building long before any of the network exists.

## The link

A link is a record both tenants hold, created by a code and endable by either side.

**The code.** The vendor's admin generates a connection code in their tenant. It is single-use, scoped to one of their companies, time-limited (24 hours is a reasonable default), and tied to the company that issued it — not to the whole group. They send it to you however they like: email, phone, on an invoice.

**Redemption.** Your admin enters the code against an existing supplier record, or creates one. Redemption binds *your* company to *their* company. A code already used, expired or revoked fails with a plain message — never a hint about which tenant it belonged to.

**Confirmation.** The issuing side sees the pending link and confirms it. Two deliberate acts, one per tenant, before anything flows. This is what stops a leaked code from silently connecting a stranger.

**Scope.** A link is between **one company on each side**. If your group buys through three companies and the vendor sells through two, that is up to six links, each consented separately. Resist the temptation to link group-to-group: it is the shortcut that later makes it impossible to say which company may see which prices.

**Ending it.** Either side can suspend or end the link at any time, without the other's agreement, and the effect is immediate: no new documents cross. Everything already exchanged stays exactly where it is, on both sides, readable forever. A quote you received does not vanish because the vendor left — you made a commercial decision on it, and the record of that decision is yours.

**Your side stays yours.** The linked supplier is still an ordinary row in your supplier table, with your code, your category, your notes, your group-sharing choice. The link adds a counterparty reference to it. Nothing about the vendor's tenant dictates how you file them — which is what makes the whole thing adoptable one vendor at a time.

### "One link per supplier record", explained

It means: **one row in your supplier table points at no more than one external company.**

It does *not* limit how many vendors you link — link a thousand. It does not stop several of your companies dealing with the same vendor; each of your companies holds its own link to them. The rule constrains one thing only: a single supplier row must not be shorthand for two different counterparties.

Why it matters. Suppose you keep one row called "Al Rabih" and link it to both *Al Rabih Trading LLC* (Dubai) and *Al Rabih Industries* (Sharjah), because to your buyer they are the same people. Then:

- An RFQ sent to "Al Rabih" has no single destination. The system cannot route it.
- A quote arrives and nothing says which company sent it.
- Their two price histories merge into one, so your historical-price column is an average of two businesses.
- Ending the link with one of them cannot be expressed.

So: **two legal entities, two supplier rows**, each linked separately, even when your buyer thinks of them as one vendor. If you want them visually grouped, that is a parent-company field on the supplier record — a reporting convenience, not an identity.

This is also why the duplicate-merge path matters before linking starts. Your table already holds 137 imported suppliers; any near-duplicates in there become ambiguous destinations the moment a link is attached to one of them.

## What crosses the boundary

The rule: **a document crosses, a database never does.** Each side keeps its own records; what passes between them is a small, explicit, versioned message.

| Crosses | Direction | Notes |
| --- | --- | --- |
| Partner profile | Both ways | Only what each side publishes to partners: legal name, country, contacts, certificates, logo. Never the full supplier record |
| Requisition for quote | You → vendor | Line description, quantity, unit, specification notes, needed-by date, incoterm, currency |
| Quote | Vendor → you | Per line: price, quantity offered, availability, lead time, substitute if any; plus validity and terms |
| Award or decline | You → vendor | The outcome, per line |
| Status events | Both ways | Received, superseded, revised, withdrawn |

What never crosses is as important:

- **Your other vendors' prices.** A vendor sees their own quote and the outcome, never the comparison. Leaking a competitor's number destroys trust in the network permanently.
- **Your internal fields.** Supplier code, category, notes, variance threshold, your group-sharing choice — all yours.
- **Their cost base.** You get their price, not what they paid.
- **Bank details.** Never over this channel, under any circumstance. Payment destination changes are the single most attacked path in B2B commerce; keep them on a verified, human-confirmed route as the supplier plan already requires.

**Your internal prices must not leak through the request.** An RFQ today carries a historical last price for comparison. That column must be stripped on the way out — if a vendor can see what you last paid, every quote converges on it.

**Specification, not identity.** You send what you want described, never your internal product ID. The vendor maps it to their own catalogue. Over time that mapping accumulates on the link and becomes the thing that makes repeat quoting fast — but it is their mapping, held on their side, confirmed by them.

## The exchange, and who owns what

The hardest question in any network like this is not transport. It is **whose record is authoritative when the two sides disagree.** Answer it once, at the start.

**Each side owns what it authored, and holds a copy of what it received.**

- Your requisition is yours. The vendor holds a received copy they cannot edit.
- Their quote is theirs. You hold a received copy you cannot edit — you can accept it, decline it, or ask for a new one, but you can never alter what they said.
- The award decision is yours, and they receive it.

That single rule removes the entire class of "but we sent you 1,800" arguments, because both sides hold the same immutable copy of each other's statements, each with a version.

**Revisions flow through, they do not overwrite.** The revision loop you already built maps onto this exactly. When you revise a sent RFQ, the vendor's copy is marked superseded and a new version arrives — their open quote stands down on their side as it does on yours, with your reason attached. Nothing is deleted on either side. A vendor who withdraws a quote does the mirror image: your copy is marked withdrawn, still readable, no longer awardable.

**A linked vendor's quote enters your existing comparison screen.** This is the point of the whole exercise: there is no separate "network quotes" area. A quote that arrived over a link and a quote your buyer typed from an email sit side by side, compared the same way, with a small marker showing which came from where. A line the vendor marked *not quoted* behaves exactly as it does today.

**Degrade gracefully.** Most vendors will never run FreightLens. A supplier may be unlinked, linked-but-unresponsive, or linked-and-active, and the buyer's screen should work identically in all three cases. The link is an accelerator, never a prerequisite — if the network path is unavailable, the manual path must still be right there.

## The shared catalogue

If the vendor maintains their products in the system, the link can carry their catalogue too — and this is the part that makes everything else work properly.

**It solves identity.** Without it, you describe a product in words and the vendor guesses which of theirs you mean. With it, you search their catalogue while writing the requisition and pick the actual item. The line then carries **their SKU**, so the quote comes back matched to the line with no description guessing, no blank-code fallback, and nothing for a buyer to reconcile by eye.

**It makes the MOQ warning possible at the right moment.** Their catalogue carries minimum order quantity, pack or carton multiple, lead time and unit of measure. Those are exactly the fields that today cause a deviation to be discovered when the quote arrives. Read from the vendor's own catalogue, the requisition screen can say "their minimum is 5" while the buyer is still typing 3 — the only moment it costs nothing to fix.

**It is published, not synced.** The vendor decides what partners see, per link: a full catalogue, one segment, or nothing. They may publish indicative prices, price-on-request, or no prices at all. A catalogue price is a reference, never an offer — **only a quote commits them**, and the screen must say so, or someone will raise a PO against a stale number.

**Map, never merge.** Their catalogue items must not flow into your product dictionary as products. Yours is your record, with your codes and your categories. Their item links to yours through `product_suppliers` — the table that already exists and already holds supplier SKU, cost, MOQ and lead time. One confirmed mapping, reusable forever. A vendor item with no counterpart in your dictionary is an *unmapped candidate* a buyer can promote deliberately, never an automatic insert.

**Hold a dated copy.** Cache what they published with a `synced_at` stamp, show it, and let a buyer refresh. Live lookups on every keystroke tie your requisition screen to their uptime.

**Degrade, as always.** No catalogue published, or no link at all, and the buyer types a description exactly as today. The catalogue is an accelerator for the vendors who invest in it — and a quiet incentive for them to do so.

## At a glance

*(A diagram of the two-tenant handshake sits here in the living copy — link at the top.)*

The code travels outside the system, which is what makes it proof of intent. Everything after that is two tenants exchanging documents neither can edit on the other's behalf.

## Best practice for building it

These are the patterns that separate a demo from something two companies trust with purchase orders.

**Exchange through an outbox, never a direct call.** When an RFQ is sent, write a row to an outbox table in the same transaction as the document, and deliver it from there. A send that fails must never leave the document saying "sent" when it is not, and a database rollback must never leave a message already delivered. This one pattern prevents the majority of distributed-system bugs in systems like this.

**Every message idempotent.** Each carries a stable id; redelivering one changes nothing. Networks retry, operators replay, and a duplicate quote arriving twice must not become two quotes.

**Version the contract from day one.** Put a schema version on every message, accept unknown fields without failing, and never change the meaning of an existing field. Two tenants upgrade at different times — that is the normal state, not an edge case.

**Tenant isolation is the security boundary.** Every read on the receiving side is scoped by the link, and that scoping is enforced in the service layer, never by the screen. Test it by calling the API directly as the wrong tenant. The single worst failure this system could have is one vendor seeing another's quote.

**Immutable receipt.** Store the exact payload received, byte for byte, alongside your interpretation of it. When a vendor says "we quoted 1,900", the answer is the stored document, not a reconstruction.

**Clock discipline.** Timestamps in UTC with the originating timezone recorded. Quote validity and RFQ deadlines are commercially meaningful, and Seychelles, the Gulf and China are not in the same day.

**Rate limits and quotas per link.** Not for scale — for blast radius. A bug in one tenant's integration should not be able to flood another's.

**Audit both sides of every crossing.** Who sent, who received, when, what version. Your existing snapshot pattern (`po_version_snapshots`) is the right model: the audit trail is the state, not a flag someone can set.

**Design the failure messages.** "Code expired", "link suspended", "vendor has not confirmed yet" are the screens users will actually meet most often. They should say what to do next, and never reveal anything about a tenant the user is not linked to.

**Data protection.** Two independent companies exchanging commercial data need a stated retention position, a named lawful basis for sharing contact details, and an export of what was exchanged. Decide this before the first external pilot, not after.

## Seams to leave now

None of this needs building yet. What it needs is for the supplier and procurement work happening now to avoid closing the doors. Each of these is cheap today and expensive to retrofit.

| Seam | Do now | Why |
| --- | --- | --- |
| **Vendor on the RFQ** | Add vendor selection to the requisition — who this is going to, as real data | The hinge. Without it there is nothing to route, and it is useful on its own |
| **Supplier SKU populated** | Capture `product_suppliers.supplier_sku` at award and at quote entry | The join key a shared catalogue maps onto. Empty today |
| **MOQ, lead time, pack multiple** | Write them back on award; warn at entry | Works manually now, and is the same field a catalogue fills later |
| **Counterparty column** | Add a nullable `linked_org_id` to the supplier record, unused | A null column now beats a migration across a live supplier table later |
| **Quote source** | Record how each quote arrived — typed, imported, or over a link | The comparison screen must show provenance. Adding it after the fact means backfilling history |
| **No internal prices in the RFQ payload** | Keep the outbound shape free of your last-paid price | If the RFQ shape is built with your prices in it, the leak ships with the first integration |
| **Snapshot on both sides of a send** | Keep the existing version-snapshot discipline for sends | Already how your revision loop works. Extending it across a boundary is then natural |

The supplier plan's P0 should also be read with this in mind. Its profile tabs — Products, Purchase orders, Quotes — are the same surfaces that will later show *linked* activity. Build them so a row can carry a provenance marker without redesign.

## Identity: codes and keys

The question "should the supplier code be a UUID?" has a clear answer: **no — because you are trying to make one identifier do four jobs.** Separate them and each becomes easy.

| Job | Use | Shape | Who sees it |
| --- | --- | --- | --- |
| Database key | `supplier_id`, as today | Integer | Nobody |
| Human reference | Supplier code | `SUP-00042` — short, speakable, group-unique | Your buyers |
| Network identity | System-issued participant ID | `FL-7K3M-9QX2` — opaque, global, with a check character | Both tenants, on documents |
| Proof of who they are | Country + tax or registration number | `SC` + registration no. | Verification and dedupe |

### On the group-plus-company code

Encoding a group part and a company part makes the code unique, but it buys uniqueness with meaning — and meaning in an identifier goes stale. A supplier created by one company and later shared across the group carries a code that now lies. A company renamed, merged or closed leaves every code that embedded it wrong. Changing the code to fix it breaks every printed PO that quoted it.

This is the classic *smart key* trap: the moment the fact you encoded changes, you must choose between a wrong identifier and a broken history. Both are bad.

**The fix is to make the scope the group, and leave the code meaningless.** Suppliers are a group-level master — 136 of your 137 are already shared — so uniqueness belongs at the group. One sequence, `SUP-00042`, unique across the group, never reused. Which company created it is a column, not a character range. If a per-company prefix is genuinely wanted for reading, make it a *display* prefix derived from the owner column at render time, so the stored identity never moves.

### Why not a UUID as the code

UUIDs are correct for machines and hostile to people. Nobody reads `f47ac10b-58cc-4372-a567-0e02b2c3d479` over the phone, types it onto a delivery note, or spots that two of them differ in one character. Keep UUIDs internal; give humans something short.

### The network identity, when you get there

The moment two independent organisations exchange documents, neither side's internal code can identify a party — both sides have their own, and both think theirs is correct. You need a third identifier that **the platform issues and neither tenant owns**:

- **Opaque.** Carries no meaning, so nothing can go stale.
- **Short and checkable.** Around 10 characters, Crockford base-32 (no `I`, `L`, `O`, `U`), with a check character so a mistyped ID fails immediately rather than resolving to a real stranger.
- **Permanent.** Issued once per organisation and per company, never reused even after an account closes.
- **Not a secret.** It names a party; it grants nothing. Access comes from the consented link, never from knowing an ID.

Alongside it, store **external identifiers** as typed rows rather than inventing your own: tax or VAT number, company registration number, and later GS1 GLN, DUNS or an LEI if you ever interoperate beyond your own platform. A supplier may hold several. These are what make deduplication and verification possible — "same country, same registration number" is a far stronger match than "similar name", and it is how every real B2B network does it.

## Phasing

| Phase | What ships | Depends on |
| --- | --- | --- |
| **0 — now** | The seams above. Vendor selection on the RFQ, supplier SKU, MOQ write-back, provenance on quotes | Nothing. All useful without any network |
| **1 — identity** | A tenant can publish a partner profile. Connection codes, two-sided consent, link lifecycle, suspend and end | The supplier plan's P0, and the `org_id` fix |
| **2 — one document** | RFQ out, quote back. Nothing else crosses. Lands in the existing comparison screen with a source marker | Phase 1 |
| **3 — catalogue** | Vendor publishes a catalogue per link; buyer picks items while writing the requisition; mapping accumulates on `product_suppliers` | Phase 2, and supplier SKU actually populated |
| **4 — the rest** | Award and decline notifications, revision propagation, order acknowledgement | Phase 2, once the exchange has run in production |
| **5 — discovery** | Verified public profiles, search, mediated contact. A different product — see the marketplace section | Phases 1–4 live, and a verification standard decided |

### What not to build yet

- **Discovery, yet.** A searchable directory is the stated long-term ambition and has its own section below — but it must not come before linking works. Linking by code is deliberate and sufficient until there is something worth discovering.
- **Invoices, payments or bank details over the link.** The highest-risk data on the slowest-to-mature channel. Keep it out indefinitely.
- **Automatic catalogue import into your dictionary.** Map, never merge — the moment vendor data flows into your product master unreviewed, your master stops being yours.
- **Two-way inventory or availability feeds.** Interesting, and a large commitment that pays nothing until phases 2 and 3 are proven.
- **A general API for third parties.** A tenant-to-tenant link inside one product is a far smaller promise than a public integration contract.

## The marketplace, further out

The longer ambition is a buyer–supplier platform: participants find each other, make contact, and begin trading without knowing each other beforehand. That is a real and reachable destination, but it is a **different product** from the private network above, and the difference is worth naming before any of it is designed.

**A private network is plumbing between parties who already trade. A marketplace is a place where trade begins.** The first succeeds if documents arrive intact. The second succeeds only if enough participants are present, which is a cold-start problem no amount of engineering solves.

### What changes, and what does not

| Stays as designed | Becomes much harder |
| --- | --- |
| Consented links; a code still binds two parties | A public profile that strangers can read — a new privacy surface |
| Document exchange and ownership rules | Trust: who is real, who is solvent, who delivers |
| Catalogue publishing, per link | Catalogue publishing to the *public*, with price exposure to competitors |
| Tenant isolation | Spam, scraping, and buyers harvesting supplier lists |
| Participant IDs and external identifiers | Verification — an ID proves identity only once someone has checked it |

### The three problems to solve, in order

**Verification before discovery.** A directory of unverified companies is worth less than no directory, because a buyer who gets burned once never returns. Decide what a verified badge means — registration number checked against a public registry, bank account confirmed, a trade reference — and who bears the cost of checking. The external-identifier rows from the identity section are the foundation.

**Liquidity before features.** A marketplace with 40 suppliers in one category is useful; one with 4,000 across 200 categories is empty everywhere. Pick a narrow wedge — the categories your own group already buys heavily — and seed it from vendors you already trade with. Your existing supplier base is the asset here, and it is a strong one.

**A reason for suppliers to show up.** Buyers want choice, suppliers want orders, and neither joins an empty room. The honest sequence is: linked vendors first, serving buyers who already chose them; then let those vendors be discoverable; only then open discovery to strangers. Each step gives the next one a population.

### Design decisions that bite early

- **Separate the public profile from the partner profile from the internal record.** Three visibility tiers, decided per field, from the first schema. Retrofitting "which of these fields is public" across a populated supplier table is painful.
- **Contact must be mediated, never raw.** Publish a contact route, not an inbox. A public email address on a supplier profile becomes a spam target within weeks, and you cannot withdraw it once it has been scraped.
- **Decide the business model before building discovery.** Listing fee, transaction fee, subscription or free — each implies different data, different reporting, and different incentives to game ranking. A marketplace that discovers its model late usually has to rebuild its ranking.
- **Ranking is a product, not a sort order.** The moment suppliers can be found, how they are ordered becomes commercially decisive and will be gamed. Plan to defend it.
- **Keep buyer demand private by default.** A buyer's requisition history is competitively sensitive. Publishing demand signals — even aggregated — is a deliberate choice, not a default.

## Decisions to settle

Each has a recommended default, so the work can start from a position rather than a question.

| Question | Recommendation |
| --- | --- |
| Link granularity: group-to-group or company-to-company? | **Company to company.** More links to manage, but the only shape that keeps prices and permissions separable later |
| Who may generate and redeem a connection code? | **An org admin on each side.** A buyer should not be able to open a data channel to another company |
| Can one supplier record be linked to more than one counterparty? | **No — one link per supplier record.** Two counterparties on one row is the duplicate problem wearing a disguise |
| What happens to in-flight documents when a link ends? | **They stop moving and stay readable.** Open RFQs are marked no longer deliverable; the buyer falls back to email |
| Does the vendor see who else was asked? | **Never.** Not the names, not the count, not the prices |
| Is a catalogue price binding? | **No. Only a quote commits.** State it on the screen wherever a catalogue price is shown |
| Who pays for the vendor's tenant? | **An open commercial question** — but it decides adoption. A vendor who must buy a licence to quote you will decline; a free quote-only tier changes the maths |
| Supplier code: a UUID, or group-plus-company segments? | **Neither.** A meaningless group-unique code for people, the existing integer key for the database, a platform-issued participant ID for the network, tax and registration numbers for proof — see the identity section |
| What does “verified” mean on a public profile? | **Registration number checked against a public registry, at minimum.** Settle it before discovery ships, not after the first fraud |

### The one to answer first

**Would your vendors actually use it?** Everything here is buildable; none of it is worth building if a vendor's purchasing team prefers email. Before phase 1, ask two or three vendors you buy from regularly whether they would log into a system to quote. Their answer sets the size of this whole programme — and the seams in the phase 0 table are worth building either way.
