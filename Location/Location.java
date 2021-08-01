package Location;

import Player.Player;

public abstract class Location {
protected String name;
protected Player player;

    public Location(Player player) {
        this.player = player;
    }


   
	public abstract boolean getLocation();


    public String getName() {
        return this.name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public Player getPlayer() {
        return this.player;
    }

    public void setPlayer(Player player) {
        this.player = player;
    }


    
}
