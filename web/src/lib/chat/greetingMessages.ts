export const GREETING_MESSAGES = [
  "Hello, How can I help you?",
  "Let's get started",
];

export function getRandomGreeting(): string {
  return GREETING_MESSAGES[
    Math.floor(Math.random() * GREETING_MESSAGES.length)
  ] as string;
}
