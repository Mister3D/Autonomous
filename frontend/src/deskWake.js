import { api } from "./api";
import { state } from "./store";

/** Wake a sleeping desk and sync the bot row in the store. */
export async function wakeBotDesk(botName) {
  const desk = await api.deskWake(botName);
  const i = state.bots.findIndex((b) => b.name === botName);
  if (i >= 0) {
    state.bots[i] = { ...state.bots[i], desk };
  }
  return desk;
}
