<template>
  <router-view />
  <div class="toast-stack" aria-live="polite">
    <div v-for="n in state.notifications" :key="n.id" class="toast">{{ n.text }}</div>
  </div>
</template>

<script setup>
import { state } from "./store";
</script>
