# Laundry Status Board

ok i want to create a very simple display for showing the status of my laundry in an industrial laundry. I imagine 3 screens: 1) its a screen split in two. on the left side it shows one big number of the shaft (911). on the right it shows a number of infos such as the Kundennummer, Trägernummer, Artikelnummer, id nummer, jahr und woche in der es eingesetzt wurde (ist eine zahl sowas wie 2008), die größe und der produktname (hose blau). der rahmen von allen screens soll immer den status grün (produkt hat keine gegenstände in der hosentasche), rot (produkt hat gegenstände in der tasche). in der top navbar des screens (sehr klein) sollte das datum, die zeit, der name der person und dessen nummer sowie die anzahl der gescannten teile stehen. Unter der großen Zahl sollte noch das gewünschte gewicht, das echte gewicht und die differenz stehen. der 2) screen zeigt dann an "please check" in großen buchstaben und darunter zwei buttons die entweder "etwas gefunden" oder "nicht gefunden" anzeigen. Wenn man auf nichts gefunden drückt kommt man zurück auf den ersten schacht und sieht wo man es reinschmeißen muss. wenn man was gefunden hat, kommt man auf den 3. screen auf dem man dann die option hat den gefundenen gegenstand als button anzudrücken (z.B. Scissors mit einem kleinem bild einer schere daneben) etc.

This project was built with [Lovable](https://lovable.dev).

**Live app**: https://smart-shaft.lovable.app

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/89a8864b-c47b-4706-9783-bebd3d7c6d01).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
