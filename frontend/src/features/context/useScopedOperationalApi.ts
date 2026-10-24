import { useMemo } from 'react';
import { useOptionalAuth } from '../../shared/auth';
import { createScopedOperationalApi, operationalApi } from './operationalApi';

export function useScopedOperationalApi() {
  const auth = useOptionalAuth();
  return useMemo(() => auth ? createScopedOperationalApi(auth.authHeaders) : operationalApi, [auth?.authHeaders]);
}
