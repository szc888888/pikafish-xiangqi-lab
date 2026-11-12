export interface HallTurnPresentation {
  moves: string[]
  pendingTurnId: string
  pendingUserUci: string | null
}

export function optimisticHallUserMove(
  moves: string[],
  userUci: string | null,
  turnId: string,
  pendingTurnId: string | null,
  pendingUserUci: string | null,
): HallTurnPresentation {
  const retryingSameMove = pendingTurnId === turnId && pendingUserUci === userUci
  return {
    moves: userUci && !retryingSameMove ? [...moves, userUci] : [...moves],
    pendingTurnId: turnId,
    pendingUserUci: userUci,
  }
}
