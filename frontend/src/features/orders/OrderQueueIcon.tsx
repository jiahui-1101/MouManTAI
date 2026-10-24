const paths = {
  orders: 'M5 4h14v17H5z M9 4V2h6v2 M8 9h8 M8 13h8 M8 17h5',
  pending: 'M12 8v4l3 2 M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
  accepted: 'm7 12 3 3 7-7 M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
  rejected: 'm9 9 6 6 m0-6-6 6 M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
  risk: 'M12 3 2 21h20z M12 9v5 M12 17v1',
  information: 'M5 3h10l4 4v14H5z M14 3v5h5 M9 12h6 M9 16h4',
  refresh: 'M20 7v5h-5 M4 17v-5h5 M5 8a8 8 0 0 1 13-3l2 3 M4 16l2 3a8 8 0 0 0 13-3',
  search: 'M16 16l5 5 M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14',
  filter: 'M4 6h16 M7 12h10 M10 18h4',
  arrow: 'M4 12h16 m-5-5 5 5-5 5',
  unavailable: 'M5 5l14 14 M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
} as const;

export function OrderQueueIcon({ name, className = '' }: { name: keyof typeof paths; className?: string }) {
  return <svg className={className} aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}
