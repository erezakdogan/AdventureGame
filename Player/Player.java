package Player;
public class Player {

   
    private String name; 
    private int id;
    private int damage;
    private int health;
    private int money;


    public Player(String Name, int id, int damage, int health, int money) {
        this.setName(Name);
        this.setId(id);        
        this.setDamage(damage);
        this.setHealth(health);
        this.setMoney(money);
    }


    public int getMoney() {
        return money;
    }


    public void setMoney(int money) {
        this.money = money;
    }


    public int getHealth() {
        return health;
    }


    public void setHealth(int health) {
        this.health = health;
    }


    public int getDamage() {
        return damage;
    }


    public void setDamage(int damage) {
        this.damage = damage;
    }


    public int getId() {
        return id;
    }


    public void setId(int id) {
        this.id = id;
    }


    public String getName() {
        return name;
    }


    public void setName(String name) {
        this.name = name;
    }

}
