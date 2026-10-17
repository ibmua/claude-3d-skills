// Stand-in for a game's shader-library binder (the private build uses the game's own idle-three.js).
// Without a library, materials that ask for library kinds report "no shader library" and keep their glTF look.
export async function loadIdleLibrary() { throw new Error('no shader library in this build'); }
export function packSlot() { throw new Error('no shader library in this build'); }
export function makeIdleMaterial() { throw new Error('no shader library in this build'); }
