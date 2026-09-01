#include <ftxui/dom/elements.hpp>
#include <ftxui/screen/screen.hpp>
#include <iostream>

int main() {
  using namespace ftxui;

  auto ticker_pane = window(text(" Ticker Panel ") | bold,
                            vbox({
                                text("BTC/USD: $64,230 (+2.4%)") | color(Color::Green),
                                text("SOL/USD: $142.10 (-0.8%)") | color(Color::Red),
                            }));

  // Replaced static text with a structured ASCII/Unicode candlestick layout
  auto chart_pane = window(text(" Chart Panel (1H Candle) ") | bold,
                           vbox({
                               text(" $65k +---------------------+") | dim,
                               text("      |      ██             |"),
                               text("      |      ██        │    |"),
                               text("      |  │   ██     [###]   |"),
                               text("      |[###] ██       ██    |"),
                               text("      |  │   ██       ██    |"),
                               text(" $63k +--│---██-------██----+") | dim,
                               text("      T1   T2   T3   T4   T5"),
                           }) | center);

  auto order_book = window(text(" Order Book ") | bold,
                           vbox({
                               text("Bid: $64,228 (1.5 BTC)") | color(Color::Green),
                               text("Ask: $64,231 (0.8 BTC)") | color(Color::Red),
                           }));

  auto logs_pane = window(text(" System Logs ") | bold,
                          vbox({
                              text("Status: ONLINE") | color(Color::Cyan),
                              text("Socket: Active"),
                          }));

  auto layout = vbox({
      hbox({
          ticker_pane | flex,
          chart_pane | flex,
      }),
      hbox({
          order_book | flex,
          logs_pane | flex,
      }),
  });

  auto screen = Screen::Create(Dimension::Full(), Dimension::Fixed(14));
  Render(screen, layout);
  screen.Print();
  std::cout << std::endl;

  return 0;
}

