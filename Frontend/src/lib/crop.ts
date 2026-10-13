/**
 * Plain-language reading of the model score. The bands are a presentation aid, not a
 * statistical claim: the score is the model's softmax output, not a calibrated probability.
 */
export function scoreNote(confidence: number, threshold: number): string {
  if (confidence < threshold) return "Low score: the model is unsure, so no result is given.";
  if (confidence < 0.85) return "Moderate score: treat this as a hint and check the leaf yourself or with an expert.";
  return "High score, but a high score can still be wrong, especially for plants or photos the model has not seen.";
}

