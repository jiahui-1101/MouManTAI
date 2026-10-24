/** Illustrative, synthetic records only. They are not API contracts or supplier claims. */
export interface SyntheticSupplier {
  id: string;
  name: string;
  category: string;
  location: string;
  offerVersion: string;
  price: string | null;
  quantity: string | null;
  unit: string | null;
  leadTime: string | null;
  evidence: string | null;
  note: string;
}

export const syntheticSuppliers: SyntheticSupplier[] = [
  { id: "demo-packaging", name: "Example Packaging Co.", category: "Food packaging", location: "Demo region A", offerVersion: "DEMO-QUOTE-01", price: "RM 0.42", quantity: "500", unit: "pcs", leadTime: "3–5 demo days", evidence: "Synthetic quotation sample", note: "No verified availability or delivery commitment." },
  { id: "demo-supply", name: "Sample General Supply", category: "General supplies", location: "Demo region B", offerVersion: "DEMO-QUOTE-02", price: null, quantity: "1", unit: "carton", leadTime: null, evidence: null, note: "Price, timing and source evidence are unknown in this sample." },
];

export const syntheticCategorySpecs = [
  { name: "Food packaging", version: "DEMO-SPEC-v1", fields: ["Food-contact declaration", "Material", "Capacity", "Pack quantity"] },
  { name: "Perishable ingredients", version: "DEMO-SPEC-v1", fields: ["Ingredient identity", "Grade", "Temperature range", "Expiry / shelf life"] },
  { name: "General supplies", version: "DEMO-SPEC-v1", fields: ["Item identity", "Dimensions", "Unit", "Pack quantity"] },
];
