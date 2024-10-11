# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 7
# Date:         10 - 09 - 2024
#
from math import *

# .'s represent empty tiles
board = [ 
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."],
    [".",".",".",".",".",".",".",".","."]
]

# Function to display the board
def dispGame(board):
    for row in board:
        print(" ".join(row))
    print()
def checkCoords(move):
    # Assuming that the inputs are ints
    move = move.strip()
    parts = move.split(" ")
    if len(parts) != 2:
        return None
    row = int(parts[0])
    col = int(parts[1])
    # Check that row and col are within bounds [0-8]
    if row < 0 or row >= 9 or col < 0 or col >= 9:
        return None
    return row, col
player = None
dispGame(board)
bMove = input("Enter the row and column of your first move, or 'stop' to quit; Black's move: ")
if bMove != "stop":
    checked = checkCoords(bMove)
    while checked is None or not (board[checked[0]][checked[1]] == "."):
        bMove = input("Invalid input, try again; Black's move: ")
        if bMove == "stop":
            print("Game has been stopped!")
            exit()
        checked = checkCoords(bMove)
    row, col = checked
    board[row][col] = chr(9675)
    dispGame(board)
    player = False
    wMove = input("White's move: ")

while bMove != "stop":
    if player:
        checked = checkCoords(bMove)
        if bMove == "stop":
            print("Game has been stopped!")
            exit()
        else:
            while checked is None or not (board[checked[0]][checked[1]] == "."):
                bMove = input("Invalid input, try again; Black's move: ")
                if bMove == "stop":
                    print("Game has been stopped!")
                    exit()
                checked = checkCoords(bMove)
            row, col = checked
            board[row][col] = chr(9675)
            dispGame(board)
            player = False
            wMove = input("White's move: ")
    else: 
        checked = checkCoords(wMove)
        if wMove == "stop":
            print("Game has been stopped!")
            exit()
        else:
            while checked is None or not (board[checked[0]][checked[1]] == "."):
                wMove = input("Invalid input, try again; White's move: ")
                if wMove == "stop":
                    print("Game has been stopped!")
                    exit()
                checked = checkCoords(wMove)
            row, col = checked
            board[row][col] = chr(9679)
            dispGame(board)
            player = True
            bMove = input("Black's move: ")
else:
    print("Game has been stopped!")
