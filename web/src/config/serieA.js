export const SERIE_A_TEAMS = [
  { id: 'napoli', name: 'Napoli' },
  { id: 'inter', name: 'Inter' },
  { id: 'milan', name: 'Milan' },
  { id: 'juventus', name: 'Juventus' },
  { id: 'roma', name: 'Roma' },
  { id: 'lazio', name: 'Lazio' },
  { id: 'atalanta', name: 'Atalanta' },
  { id: 'fiorentina', name: 'Fiorentina' },
  { id: 'bologna', name: 'Bologna' },
  { id: 'torino', name: 'Torino' },
  { id: 'genoa', name: 'Genoa' },
  { id: 'monza', name: 'Monza' },
  { id: 'lecce', name: 'Lecce' },
  { id: 'udinese', name: 'Udinese' },
  { id: 'cagliari', name: 'Cagliari' },
  { id: 'empoli', name: 'Empoli' },
  { id: 'verona', name: 'Verona' },
  { id: 'sassuolo', name: 'Sassuolo' },
]

/** Mapping squadra → giocatori/allenatori per filtrare claim correlati */
export const TEAM_ROSTER = {
  napoli: {
    players: ['Di Lorenzo', 'Osimhen', 'Kvaratskhelia', 'Kvara', 'Lorenzo', 'Politano', 'Raspadori', 'Elmas', 'Lobotka', 'Anguissa', 'Lukaku'],
    coaches: ['Conte', 'Spalletti']
  },
  inter: {
    players: ['Lautaro', 'Martinez', 'Bastoni', 'Barella', 'Dimarco', 'Thuram'],
    coaches: ['Inzaghi', 'Simone Inzaghi']
  },
  milan: {
    players: ['Leao', 'Giroud', 'Maignan', 'Theo Hernandez'],
    coaches: ['Pioli']
  },
  juventus: {
    players: ['Vlahovic', 'Chiesa', 'Szczesny'],
    coaches: ['Allegri', 'Thiago Motta']
  },
  roma: {
    players: ['Dybala', 'Lukaku', 'Pellegrini'],
    coaches: ['De Rossi', 'Mourinho']
  },
  lazio: {
    players: ['Immobile', 'Zaccagni'],
    coaches: ['Tudor', 'Sarri']
  },
  atalanta: { players: [], coaches: ['Gasperini'] },
  fiorentina: { players: [], coaches: ['Italiano'] },
  bologna: { players: [], coaches: ['Thiago Motta'] },
  torino: { players: [], coaches: ['Juric'] },
  genoa: { players: [], coaches: [] },
  monza: { players: [], coaches: [] },
  lecce: { players: [], coaches: [] },
  udinese: { players: [], coaches: [] },
  cagliari: { players: [], coaches: [] },
  empoli: { players: [], coaches: [] },
  verona: { players: [], coaches: [] },
  sassuolo: { players: [], coaches: [] },
}
