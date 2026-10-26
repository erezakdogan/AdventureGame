package Player;

public class Inventory {
    private boolean water,food,firewood;
	private String wName,aName;
	private int damage,armor;
    private boolean[] wp= {false,false,false};
    private boolean[] arm= {false,false,false};
    private boolean[] coi= {false,false,false};

  

   

    public Inventory() {
        this.water = false;
        this.food = false;
        this.firewood = false;
        
        this.wName = null;
        this.aName = null;
        this.damage = 0;
        this.armor = 0;
    }

    public boolean[] getWp() {
        return this.wp;
    }

    public void setWp(boolean[] wp,Player player) {
        this.wp = wp;
        if(wp[2]){
			wName = "Tüfek";
            player.setDamage(player.getDamage()+7);
            setWName(wName);
        }else if(wp[1]){
			wName = "Kýlýç";
            player.setDamage(player.getDamage()+3);
            setWName(wName);
           
        }else if(wp[0]){
			wName = "Tabanca";
            
            player.setDamage(player.getDamage()+2);
            setWName(wName);
        }
        
    }

    public boolean[] getArm() {
        return this.arm;
    }

    public void setArm(boolean[] arm,Player player) {
        this.arm = arm;
        if(arm[2]){
            aName = "Aðýr Zýrh";
            setArmor(5);
            setAName(aName);
        }else if(arm[1]&&(getAName()!="Aðýr Zýrh")){
            aName = "Orta Zýrh";
            setArmor(3);
            setAName(aName);
        }else if(arm[0]&&(getAName()!="Aðýr Zýrh")){
            aName = "Hafif Zýrh";
            setArmor(1);
            setAName(aName);
        }
    }

    public boolean[] getCoi() {
        return this.coi;
    }

    public void setCoi(boolean[] coi,Player player) {
        this.coi = coi;
        
        if(coi[2]){
            player.setMoney(player.getMoney()+10);
        }else if(coi[1]){
            player.setMoney(player.getMoney()+5);
        }else if(coi[0]){
            player.setMoney(player.getMoney()+1);
        }
    }

    public boolean isWater() {
        return this.water;
    }

    public boolean getWater() {
        return this.water;
    }

    public void setWater(boolean water) {
        this.water = water;
    }

    public boolean isFood() {
        return this.food;
    }

    public boolean getFood() {
        return this.food;
    }

    public void setFood(boolean food) {
        this.food = food;
    }

    public boolean isFirewood() {
        return this.firewood;
    }

    public boolean getFirewood() {
        return this.firewood;
    }

    public void setFirewood(boolean firewood) {
        this.firewood = firewood;
    }

    public String getWName() {
        return this.wName;
    }

    public void setWName(String wName) {
        this.wName = wName;
    }

    public String getAName() {
        return this.aName;
    }

    public void setAName(String aName) {
        this.aName = aName;
    }

    public int getDamage() {
        return this.damage;
    }

    public void setDamage(int damage) {
        this.damage = damage;
    }

    public int getArmor() {
        return this.armor;
    }

    public void setArmor(int armor) {
        this.armor = armor;
    }
	
    
}
