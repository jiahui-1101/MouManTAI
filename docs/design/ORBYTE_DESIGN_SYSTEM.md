# MouManTAI — Orbyte-Aligned Frontend Design System

## 1. Purpose

MouManTAI's frontend follows the visual language of the Orbyte platform while retaining its own branding, business features and workflows.

This document is the source of truth for existing and future frontend components across P1–P5.

Use the Orbyte screenshots as visual references, not as functional specifications. Do not copy Orbyte's logo, data or business functionality.

## 2. Visual References

Screenshots are stored in `docs/design/references/`:

- `client-list.png` — Tables, lists, search, pagination and row actions.
- `dashboard.png` — Overview, pending actions, grouped workflows and navigation.
- `task-reporting.png` — KPI cards, filters, progress indicators and reports.
- `task-detail.png` — Detailed records, checklists and structured information.

Read only the screenshot relevant to the current component or feature. Do not repeatedly load all screenshots.

If filenames differ, locate the corresponding reference by its content. Do not invent missing reference files.

## 3. Design Tokens

The following values were obtained from Orbyte's computed styles and CSS variables unless identified as implementation guidance.

### Colors

| Token             | Value                   | Usage                                       |
| ----------------- | ----------------------- | ------------------------------------------- |
| Primary           | `#0767E8`               | Primary buttons, links, selected navigation |
| Primary Light     | `#3885EC`               | Light blue accents                          |
| Primary Dark      | `#065CD0`               | Darker primary states                       |
| Background        | `#F4F8FF`               | Main workspace                              |
| Surface           | `#FFFFFF`               | Sidebar, cards, tables                      |
| Text Base         | `#1C3153`               | Base text color                             |
| Text Primary      | `rgba(28,49,83,0.9)`    | Main text                                   |
| Text Secondary    | `rgba(28,49,83,0.7)`    | Supporting text                             |
| Divider           | `rgba(28,49,83,0.12)`   | Borders and separators                      |
| Input Border      | `rgba(28,49,83,0.22)`   | Form fields                                 |
| Secondary         | `#808390`               | Secondary controls                          |
| Success           | `#28C76F`               | Successful states                           |
| Warning           | `#FF9F43`               | Warning states                              |
| Error             | `#FF4C51`               | Error and destructive actions               |
| Info              | `#08C7D9`               | Informational states                        |
| Progress Track    | `#E8F0FB`               | Progress backgrounds                        |
| Navigation Active | `rgba(7,103,232,0.094)` | Active sidebar items                        |

### Typography

- Font family: Public Sans, with system sans-serif fallback.
- Body: 15px, weight 400, line-height 22px.
- Page heading: 28px, weight 500, line-height 42px.
- Primary button: 15px, weight 700.
- Table headers: approximately 14px, bold.
- KPI values: approximately 24px or larger, bold.
- Use a consistent typography hierarchy across all pages.

### Radius and Shadows

- Default radius: 6px.
- Sidebar navigation radius: 8px.
- Small radius: 4px.
- Large radius: 10px.
- Primary button height: 42px.
- Primary button padding: 8px 12px.
- Primary button shadow: `0 2px 6px rgba(7,103,232,0.3)`.
- Medium shadow token: `0 3px 12px rgba(28,49,83,0.14)`.

Apply shadows contextually. Do not add shadows to every element.

## 4. Global Layout

- White desktop sidebar with logo, navigation and active item highlighting.
- Pale blue workspace background.
- White cards and content panels.
- Consistent page headings, descriptions and action alignment.
- Subtle borders and restrained shadows.
- Responsive navigation on smaller screens.
- Clear spacing between sections.

Preserve MouManTAI's existing page structure when it serves the workflow well.

## 5. Component Patterns

### Tables and Lists

Reference: `client-list.png`

Use for Inbox, Orders, Messages, Communication History and Activity Log.

- Search and filters above the table.
- White table container.
- Bold headers and subtle row separators.
- Status badges.
- Row actions aligned to the right.
- Pagination and record count when appropriate.
- Responsive horizontal scrolling.
- Loading, empty and error states.

### Dashboards and Overviews

Reference: `dashboard.png`

Use for Overview, Pending Actions, Review Queues and cross-module summaries.

- Clear heading and contextual information.
- KPI or summary cards when useful.
- Grouped pending actions.
- Expandable detail sections.
- Contextual links and actions.
- Prioritize actionable information.

### Reports and Analytics

Reference: `task-reporting.png`

Use for Feasibility, Recovery Impact and Operational Analytics.

- KPI summary cards.
- Filters and search.
- Progress bars only for meaningful metrics.
- Grouped result cards.
- Clearly labeled numerical values.
- Detailed evidence and explanations.

Never invent metrics or percentages.

### Record Details and Workflows

Reference: `task-detail.png`

Use for Order Context, Human Review, Feasibility Details, Recovery Options and Commitments.

- Clear record identity and status.
- Structured sections and supporting evidence.
- Editable and read-only fields clearly distinguished.
- Contextual actions.
- Explicit confirmation for consequential operations.
- Preserve multi-item data and complete workflow state.

## 6. Reusable Components

Prefer existing shared components. Reuse or extend them instead of creating duplicate implementations.

Common components may include:

- AppShell and Sidebar
- PageHeader and Breadcrumbs
- Button and IconButton
- DataTable and Pagination
- StatusBadge
- SearchField and FilterBar
- ContentCard and KPIStatCard
- ProgressBar
- DetailPanel and WorkflowSection
- ConfirmationDialog
- LoadingState, EmptyState and ErrorState

Use the project's existing framework and styling conventions. Avoid unnecessary dependencies.

## 7. Semantic Status Styling

Use the verified Orbyte palette while choosing semantic colors according to the actual business state.

- Blue: primary actions, active navigation and informational progress.
- Green: success, confirmed or completed.
- Orange: warning or attention required.
- Red: error, blocked or destructive actions.
- Cyan/teal: informational or workflow-specific states.
- Gray: neutral, inactive or secondary states.

Do not represent different business states as equivalent merely because their colors are similar. Keep text labels visible; color alone must not communicate status.

## 8. Functional and Technical Boundaries

This design system controls frontend presentation, not backend behavior.

- Preserve existing P1–P5 workflows.
- Preserve API integration, authentication and tenant isolation.
- Preserve validations and Human Review safeguards.
- Use real application data.
- Do not replace production data with screenshot examples or mock values.
- Do not change API contracts or database schemas for visual redesign.
- Maintain accessibility, keyboard navigation and visible focus.
- Support responsive layouts.
- Keep existing loading, error and empty states functional.

## 9. Future Feature Rule

For every new frontend feature:

1. Identify the actual user workflow.
2. Select the closest matching Orbyte-inspired layout pattern.
3. Reuse the shared components and tokens.
4. Consult only relevant screenshots if visual clarification is needed.
5. Adapt the layout to MouManTAI's real data and actions.
6. Preserve functionality and responsive behavior.

Do not force every page into the same layout. Visual consistency comes from shared typography, colors, components, spacing and interaction patterns.

## 10. Visual Acceptance Criteria

A completed frontend feature should:

- Look visually consistent with the supplied Orbyte references.
- Use the shared design tokens.
- Reuse established components.
- Preserve MouManTAI branding.
- Display actual data and meaningful statuses.
- Have functional navigation and actions.
- Work on desktop and mobile.
- Remain accessible and readable.
- Avoid unrelated backend or business logic changes.
