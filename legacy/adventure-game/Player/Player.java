package Player;

import java.util.Scanner;

public class Player {

    Scanner scan = new Scanner(System.in);
    private String name; 
    private Inventory inv;
    private int money;
    private int health;
    private int healthy;
    private int damage;

    public Player(String name) {
		this.name = name;
		this.inv = new Inventory();
	}

    public void selectCha() {
		switch (chaMenu()) {
		case 1:
			initPlayer("Samuray", 5, 21, 15);
			break;
		case 2:
			initPlayer("Okçu", 7, 18, 20);
			break;
		case 3:
			initPlayer("Şovalye", 8, 24, 5);
			break;
		default:
			initPlayer("Samuray", 5, 21, 15);
			break;
		}
		System.out.println("Karakter Oluşturuldu ! Adı=" + getName() + " ,Hasar=" + getDamage() + " ,Sağlık="
				+ getHealth() + " ,Para=" + getMoney());
	}

	public int chaMenu() {
		System.out.println("Lütfen bir karakter seçiniz : ");
		System.out.println("1- Samuray \t Hasar : 5 \t Sağlık :21 \t Para :15");
		System.out.println("2- Okçu \t Hasar : 7 \t Sağlık :18 \t Para :20");
		System.out.println("3- Şovalye \t Hasar : 8 \t Sağlık :24 \t Para :5");
		System.out.print("Karater Seçiminiz : ");
		int chaID = scan.nextInt();

		while (chaID < 1 || chaID > 3) {
			System.out.print("Lütfen geçerli bir karakter seçiniz : ");
			chaID = scan.nextInt();
		}

		return chaID;
	}

    public void initPlayer(String cName, int dmg, int hlthy, int mny) {
		setName(cName);
		setDamage(dmg);
		setHealth(hlthy);
		setMoney(mny);
        setHealthy(hlthy);
        
	}




    public String getName() {
        return this.name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public Inventory getInv() {
        return this.inv;
    }

    public void setInv(Inventory inv) {
        this.inv = inv;
    }

    public int getMoney() {
        return this.money;
    }

    public void setMoney(int money) {
        this.money = money;
    }

    public int getHealth() {
        return this.health;
    }

    public void setHealth(int health) {
        this.health = health;
    }

    public int getDamage() {
        return this.damage;
    }

    public void setDamage(int damage) {
        this.damage = damage;
    }

    public int getHealthy() {
        return this.healthy;
    }

    public void setHealthy(int healthy) {
        this.healthy = healthy;
    }
    


}
