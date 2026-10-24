import { describe, expect, it } from 'vitest';
import { parseDeliveryString } from './RequestedDeliveryField';

describe('saved delivery time display', () => {
  it('reopens a UTC-normalized backend value as the same Malaysia wall time', () => {
    expect(parseDeliveryString('2026-10-28T02:00:00Z')).toMatchObject({
      date: '2026-10-28', hour12: '10', minute: '00', ampm: 'AM', offset: '+08:00',
    });
  });

  it('handles a timezone conversion that crosses midnight', () => {
    expect(parseDeliveryString('2026-10-27T17:30:00Z')).toMatchObject({
      date: '2026-10-28', hour12: '01', minute: '30', ampm: 'AM',
    });
  });
});
