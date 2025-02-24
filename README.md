# Begin
## Project directory must contain .env file with given in example.env variables to start your coding.

## To begin you need to up compose stack using:
    docker compose -f compose_stack.yml up -d

### Your application container name will correspond with "project_slug": baselinker_to_wix

## if you need to recreate services use '--build' flag

    docker compose -f compose_stack.yml up --build -d

## even can explicitly point which one by means of:

    docker compose -f compose_stack.yml up --build baselinker_to_wix

## to make migration you can execute command inside docker app container like this:

    docker container exec baselinker_to_wix_app poetry run alembic upgrade head
**'poetry run'** part is needed because pure dockerfile creates environment inside the container. There is no need to do it
but that's my preference


# Create a GitHub Repo

Go to your GitHub account and create a new repo that matches the **baselinker_to_wix** 
Back to your CLI, you can do the following in the root of your generated project:
    
    git init
    git add .
    git commit -m "Initial skeleton."
    git remote add origin git@github.com:<MY_USERNAME>/<MY-REPO-SLUG>.git
    git push -u origin master

### When trying to install dependency using poetry on Kubuntu 22.10 
I encounter **[org.freedesktop.DBus.Error.UnknownMethod]** error. For me it can be resolved in a three way:
Running export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring in shell will work for following poetry commands until you close (exit) your shell session

Add environment variable for each! poetry command, for example PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry install

If you want to preserve (store) this environment variable between shell sessions or system reboot you can add it in .bashrc and .profile example for bash shell:

    echo 'export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring' >> ~/.bashrc

    echo 'export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring' >> ~/.profile  exec "$SHELL"

