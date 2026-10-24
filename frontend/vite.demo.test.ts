// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import configure from './vite.config';

afterEach(() => vi.unstubAllEnvs());

async function proxy(command: 'serve' | 'build', mode: string, flag: string) {
  vi.stubEnv('VITE_ORDERS_DEMO', flag);
  const config = await (typeof configure === 'function' ? configure({ command, mode }) : configure);
  return config.server?.proxy;
}

describe('local Orders demo proxy isolation', () => {
  it('routes only explicit demo reads to 8001, keeping shared APIs on 8000', async () => {
    const routes = await proxy('serve', 'demo', '1');
    expect(routes?.['/v1/demo/orders']).toBe('http://127.0.0.1:8001');
    expect(routes?.['/v1']).toBe('http://127.0.0.1:8000');
    expect(routes?.['/v1/contexts']).toBe('http://127.0.0.1:8000');
    expect(routes?.['/health']).toBe('http://127.0.0.1:8000');
    expect(Object.keys(routes ?? {}).indexOf('/v1/demo/orders')).toBeLessThan(Object.keys(routes ?? {}).indexOf('/v1'));
  });

  it.each([
    ['serve', 'development', '1'], ['serve', 'demo', '0'],
    ['serve', 'production', '1'], ['build', 'demo', '1'], ['build', 'production', '1'],
  ] as const)('does not enable the proxy for %s / %s / flag=%s', async (command, mode, flag) => {
    const routes = await proxy(command, mode, flag);
    expect(routes?.['/v1/demo/orders']).toBeUndefined();
    expect(routes?.['/v1']).toBe('http://127.0.0.1:8000');
  });
});
