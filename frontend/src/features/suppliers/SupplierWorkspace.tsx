import { Link } from "react-router-dom";
import { ContentCard, PageHeader } from "../../shared/ui";
import "./suppliers.css";

function SupplierUnavailable() {
  return <ContentCard><p role="status">Supplier data unavailable: no database-backed supplier directory or offer API is connected.</p><p>Availability, prices, quantities, performance and compatibility cannot be assessed without authorized source records.</p></ContentCard>;
}

export function SupplierDirectoryPage() {
  return <div className="supplier-workspace">
    <PageHeader title="Supplier directory" actions={<Link className="btn btn-secondary" to="/suppliers/compare">Offer comparison</Link>} />
    <SupplierUnavailable />
  </div>;
}

export function SupplierDetailPage() {
  return <div className="supplier-workspace">
    <PageHeader title="Supplier details unavailable" actions={<Link className="btn btn-secondary" to="/suppliers">Back to directory</Link>} />
    <SupplierUnavailable />
  </div>;
}

export function SupplierComparisonPage() {
  return <div className="supplier-workspace">
    <PageHeader title="Offer comparison" />
    <SupplierUnavailable />
    <ContentCard title="Requirement assessment"><p>UNKNOWN — not assessed. No approved requirement set or backend comparison contract is available.</p>
      <button className="btn btn-secondary" type="button" disabled aria-describedby="selection-unavailable">Select supplier (unavailable)</button>
      <p id="selection-unavailable">Selection is unavailable: no approved versioned offer-selection command, authorization, or audit contract exists.</p>
    </ContentCard>
  </div>;
}
