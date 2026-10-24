import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ContentCard, EvidenceTierBadge, PageHeader, SearchField, StatusBadge } from "../../shared/ui";
import { syntheticCategorySpecs, syntheticSuppliers } from "./supplierFixtures";
import "./suppliers.css";

function DemoNotice() {
  return <aside className="supplier-demo-notice" role="note"><EvidenceTierBadge evidenceTier="DEMO-ONLY" integrationMode="SYNTHETIC" /><strong>Illustrative data only.</strong> No supplier directory or offer API is connected. These records do not establish identity, availability, compatibility, delivery, or a real quotation.</aside>;
}

export function SupplierDirectoryPage() {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => syntheticSuppliers.filter((supplier) => `${supplier.name} ${supplier.category} ${supplier.location}`.toLowerCase().includes(search.toLowerCase())), [search]);
  return <div className="supplier-workspace">
    <PageHeader title="Supplier directory" description="Browse the supplier workspace and inspect sample offer fields." actions={<Link className="btn btn-secondary" to="/suppliers/compare">Compare sample offers</Link>} />
    <DemoNotice />
    <SearchField id="supplier-search" label="Search sample suppliers" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, category, or location" />
    {filtered.length ? <div className="supplier-grid">{filtered.map((supplier) => <ContentCard key={supplier.id} className="supplier-card">
      <div className="supplier-card-title"><h3><Link to={`/suppliers/${supplier.id}`}>{supplier.name}</Link></h3><StatusBadge state="UNKNOWN" label="Availability unknown" /></div>
      <p>{supplier.category} · {supplier.location}</p><p>Sample offer: {supplier.offerVersion}</p><p>{supplier.note}</p>
      <Link to={`/suppliers/${supplier.id}`}>View sample details</Link>
    </ContentCard>)}</div> : <ContentCard><p role="status">No sample suppliers match “{search}”.</p></ContentCard>}
  </div>;
}

export function SupplierDetailPage() {
  const { id } = useParams();
  const supplier = syntheticSuppliers.find((item) => item.id === id);
  if (!supplier) return <div className="supplier-workspace"><PageHeader title="Supplier sample not found" /><p role="status">This sample record is unavailable.</p><Link to="/suppliers">Back to supplier directory</Link></div>;
  const spec = syntheticCategorySpecs.find((item) => item.name === supplier.category);
  return <div className="supplier-workspace">
    <PageHeader title={supplier.name} description="Supplier sample detail" actions={<Link className="btn btn-secondary" to="/suppliers">Back to directory</Link>} />
    <DemoNotice />
    <ContentCard title="Identity and availability"><dl className="supplier-facts"><dt>Category</dt><dd>{supplier.category}</dd><dt>Location</dt><dd>{supplier.location}</dd><dt>Availability</dt><dd><StatusBadge state="UNKNOWN" label="Not verified" /></dd><dt>Performance history</dt><dd>Insufficient data — no verified delivery records</dd></dl></ContentCard>
    <ContentCard title="Category specification sample"><p>Version: <code>{spec?.version ?? "SPEC_UNKNOWN"}</code> · This illustrative field list is not an approved or connected CategorySpec.</p><ul>{spec?.fields.map((field) => <li key={field}>{field} — <StatusBadge state="UNKNOWN" label="Not provided" /></li>)}</ul></ContentCard>
    <ContentCard title="Latest sample offer"><p>Offer version: {supplier.offerVersion}</p><dl className="supplier-facts"><dt>Price</dt><dd>{supplier.price ?? "UNKNOWN"}</dd><dt>Quantity / unit</dt><dd>{supplier.quantity && supplier.unit ? `${supplier.quantity} ${supplier.unit}` : "UNKNOWN"}</dd><dt>Lead time</dt><dd>{supplier.leadTime ?? "UNKNOWN"}</dd><dt>Evidence</dt><dd>{supplier.evidence ?? "No evidence attached"}</dd></dl><p>{supplier.note}</p></ContentCard>
  </div>;
}

export function SupplierComparisonPage() {
  return <div className="supplier-workspace">
    <PageHeader title="Offer comparison" description="Inspect supplied fields side by side; no ranking or compatibility calculation is available." />
    <DemoNotice />
    <ContentCard title="Requirement assessment"><p>No approved requirement set or backend comparison contract is available. Compatibility is <StatusBadge state="UNKNOWN" label="UNKNOWN — not assessed" />. Different or missing units must not be normalized by this screen.</p></ContentCard>
    <div className="supplier-compare-grid">{syntheticSuppliers.map((supplier) => <ContentCard key={supplier.id} title={supplier.name}>
      <p>Offer {supplier.offerVersion}</p><dl className="supplier-facts"><dt>Category</dt><dd>{supplier.category}</dd><dt>Price</dt><dd>{supplier.price ?? "UNKNOWN"}</dd><dt>Quantity</dt><dd>{supplier.quantity ?? "UNKNOWN"}</dd><dt>Unit</dt><dd>{supplier.unit ?? "UNKNOWN"}</dd><dt>Lead time</dt><dd>{supplier.leadTime ?? "UNKNOWN"}</dd><dt>Evidence</dt><dd>{supplier.evidence ?? "Missing"}</dd></dl><p>{supplier.note}</p>
      <button className="btn btn-secondary" type="button" disabled aria-describedby="selection-unavailable">Select supplier (unavailable)</button>
    </ContentCard>)}</div>
    <p id="selection-unavailable" className="supplier-selection-note">Selection is unavailable: no approved versioned offer-selection command, authorization, or audit contract exists.</p>
  </div>;
}
