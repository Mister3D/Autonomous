<template>
  <div class="av-picker">
    <div class="av-picker-preview">
      <CompanionAvatar
        :character="character"
        :color="color"
        state="work"
        size="lg"
      />
    </div>

    <div class="av-picker-section">
      <p class="av-picker-label">{{ characterLabel }}</p>
      <div class="av-picker-chars" role="listbox" :aria-label="characterLabel">
        <button
          v-for="id in CHARACTER_IDS"
          :key="id"
          type="button"
          class="av-picker-char"
          :class="{ on: id === character }"
          :title="titleOf(id)"
          role="option"
          :aria-selected="id === character"
          @click="setCharacter(id)"
        >
          <CompanionAvatar
            :character="id"
            :color="color"
            :state="id === character ? 'notify' : 'idle'"
            size="sm"
          />
        </button>
      </div>
    </div>

    <div class="av-picker-section">
      <p class="av-picker-label">{{ colorLabel }}</p>
      <div class="av-picker-swatches" role="listbox" :aria-label="colorLabel">
        <button
          v-for="(sw, i) in SWATCHES"
          :key="i"
          type="button"
          class="av-picker-swatch"
          :class="{ on: i === color, 'is-original': sw[1] == null }"
          :title="sw[0]"
          :style="{ background: swatchButtonBackground(sw) }"
          role="option"
          :aria-selected="i === color"
          @click="setColor(i)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import CompanionAvatar from "./CompanionAvatar.vue";
import { CATALOG, CHARACTER_IDS } from "./catalog.js";
import { SWATCHES, swatchButtonBackground } from "./swatches.js";

const props = defineProps({
  character: { type: String, required: true },
  color: { type: Number, default: 0 },
  characterLabel: { type: String, default: "Personnage" },
  colorLabel: { type: String, default: "Couleur" },
});

const emit = defineEmits(["update:character", "update:color"]);

const character = computed({
  get: () => props.character,
  set: (v) => emit("update:character", v),
});
const color = computed({
  get: () => props.color,
  set: (v) => emit("update:color", v),
});

function titleOf(id) {
  return CATALOG[id]?.title || id;
}

function setCharacter(id) {
  character.value = id;
}

function setColor(i) {
  color.value = i;
}
</script>

<style scoped>
.av-picker {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.av-picker-preview {
  width: 120px;
  height: 120px;
  margin: 0 auto;
  border-radius: 0;
  overflow: visible;
  background: transparent;
}
.av-picker-preview :deep(.companion-avatar) {
  width: 100%;
  height: 100%;
}
.av-picker-label {
  margin: 0 0 0.45rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: #5a6170;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.av-picker-chars {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.4rem;
}
.av-picker-char {
  aspect-ratio: 1;
  border: 2px solid transparent;
  border-radius: 10px;
  padding: 0;
  background: transparent;
  cursor: pointer;
  overflow: visible;
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 0;
}
.av-picker-char :deep(.companion-avatar) {
  width: 92%;
  height: 92%;
}
.av-picker-char.on {
  border-color: #22252c;
}
.av-picker-char:hover {
  border-color: #9aa1b2;
}
.av-picker-char.on:hover {
  border-color: #22252c;
}
.av-picker-swatches {
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  gap: 0.4rem;
}
.av-picker-swatch {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px #ccd;
  cursor: pointer;
  padding: 0;
}
.av-picker-swatch.on {
  box-shadow: 0 0 0 2px #22252c;
}
@media (max-width: 480px) {
  .av-picker-chars {
    grid-template-columns: repeat(4, 1fr);
  }
  .av-picker-swatches {
    grid-template-columns: repeat(6, 1fr);
  }
}
</style>
