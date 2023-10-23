import discord


class KlatringAttendance:
    def __init__(self):
        self.defaultMessage = "@everyone Hva sker der? er i.. er i glar?\n"

        self.embed = discord.Embed(
            title="Klatretid!",
            description=self.defaultMessage)
        self.embed.set_image(url="https://i.imgur.com/9uMGPae.gif")
        self.slackers = []
        self.godsAmongMen = []

    def set_message(self, discord_message):
        self.message = discord_message

    def add_attendee(self, user):
        if (user in self.slackers):
            self.slackers.remove(user)
        if (user in self.godsAmongMen):
            return
        self.godsAmongMen.append(user)

    def add_slacker(self, user):
        if (user in self.godsAmongMen):
            self.godsAmongMen.remove(user)
        if (user in self.slackers):
            return
        self.slackers.append(user)

    def get_embed(self):
        if (len(self.slackers) == 0 and len(self.godsAmongMen) == 0):
            self.embed.description = self.defaultMessage
        else:
            self.embed.description = self.get_message()
        return self.embed

    def get_message(self):
        return f"{self.defaultMessage} \n✅: {', '.join([u.global_name for u in self.godsAmongMen])}\n❌: {', '.join([u.global_name for u in self.slackers])}"
