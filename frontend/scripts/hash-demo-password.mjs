/** Read a password from stdin; output only its scrypt verifier. */
import { randomBytes, scryptSync } from 'node:crypto';

let password = '';
for await (const chunk of process.stdin) password += chunk.toString();
password = password.replace(/\r?\n$/, '');
if (password.length < 16 || password.length > 1024) {
  console.error('Use a unique password of 16–1024 characters on stdin.');
  process.exit(1);
}
const salt = randomBytes(32);
const digest = scryptSync(password, salt, 64, { N: 16384, r: 8, p: 1 });
console.log(`scrypt$16384$8$1$${salt.toString('hex')}$${digest.toString('hex')}`);
